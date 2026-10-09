"""Local LLM layer (Ollama). Nothing leaves the machine.

Rule for the whole harness: the LLM *proposes*, a deterministic oracle *disposes*.
The model is used where hand-written rules do not generalise to a new site:

  - navigating a journey from a plain-English intent        (personas.Agent)
  - extracting urgency / scarcity claims from page text     (checks.falsity; quotes are grounded)
  - judging wording: confirm shaming, consent phrasing      (oracles, marked "Judged")
  - a screenshot-only VLM baseline, the state of the art we compare against   (vlm_baseline)

Prices, order contents, membership, consent state, inventory and click counts are always decided
by deterministic code. Every call has a fallback, so the harness also runs with no model at all.
Responses are cached on disk (.llm_cache/) so demo reruns are fast and reproducible.
"""
import hashlib
import json
import os
import re
import time

import requests

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# First installed model wins unless DP_LLM_MODEL / DP_VLM_MODEL is set.
TEXT_PREFS = ("qwen3.5:35b-a3b", "gpt-oss:20b", "qwen2.5:32b", "qwen2.5:14b", "qwen2.5:7b-instruct", "llama3.3:70b")
VISION_PREFS = ("qwen3.5:35b-a3b", "qwen2.5vl:32b", "qwen2.5vl:7b", "llava:13b")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".llm_cache")

_models = None
STATS = {"calls": 0, "cached": 0, "seconds": 0.0, "failures": 0, "by_task": {}}


def _installed() -> dict:
    """name -> capabilities for every model Ollama has pulled ({} if Ollama is unreachable or disabled)."""
    global _models
    if _models is None:
        _models = {}
        if not os.environ.get("DP_NO_LLM"):
            try:
                tags = requests.get(f"{OLLAMA}/api/tags", timeout=2).json()
                _models = {m["name"]: m.get("capabilities") or [] for m in tags.get("models", [])}
            except Exception:
                pass
    return _models


def _pick(env, prefs, need=None):
    have = _installed()
    want = os.environ.get(env)
    if want:
        return want if want in have else None
    for m in prefs:
        if m in have and (need is None or need in have[m]):
            return m
    return None


def text_model():
    return _pick("DP_LLM_MODEL", TEXT_PREFS)


def vision_model():
    if os.environ.get("DP_NO_VLM"):
        return None
    return _pick("DP_VLM_MODEL", VISION_PREFS, need="vision")


def available() -> bool:
    return text_model() is not None


def backend_name() -> str:
    m = text_model()
    return f"Ollama · {m} (local)" if m else "deterministic heuristics (no local LLM reachable)"


def _parse(s: str):
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        return json.loads(m.group(0))


def ask_json(prompt: str, *, task: str, schema: dict | None = None, images=None, model=None, system=None,
             think: bool = False):
    """One JSON answer from a local model. Raises on failure; callers fall back to deterministic code."""
    model = model or text_model()
    if not model:
        raise RuntimeError("no local model")
    # Some Ollama/model combinations (qwen3.5 with think=false) do not enforce `format`, so the schema is also
    # stated in the prompt and the reply is validated below.
    prompt += "\n\nRespond with only a JSON object" + (f" matching this JSON schema: {json.dumps(schema)}" if schema else ".")
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt, **({"images": list(images)} if images else {})}]
    body = {"model": model, "messages": msgs, "stream": False, "think": think,
            "format": schema or "json", "options": {"temperature": 0, "seed": 7, "num_ctx": 8192}}
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    path = os.path.join(CACHE_DIR, key[:2], key + ".json")
    t = STATS["by_task"].setdefault(task, {"calls": 0, "cached": 0, "seconds": 0.0})
    STATS["calls"] += 1
    t["calls"] += 1
    if os.environ.get("DP_LLM_CACHE", "1") != "0" and os.path.exists(path):
        STATS["cached"] += 1
        t["cached"] += 1
        with open(path) as f:
            return json.load(f)
    start = time.time()
    try:
        r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=300)
        r.raise_for_status()
        out = _parse(r.json()["message"]["content"])
        missing = [k for k in (schema or {}).get("required", []) if k not in out]
        if missing:
            raise ValueError(f"model reply missing {missing}")
    except Exception:
        STATS["failures"] += 1
        raise
    finally:
        dt = time.time() - start
        STATS["seconds"] += dt
        t["seconds"] += dt
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def stats() -> dict:
    return {**STATS, "seconds": round(STATS["seconds"], 1), "text_model": text_model(), "vision_model": vision_model(),
            "by_task": {k: {**v, "seconds": round(v["seconds"], 1)} for k, v in STATS["by_task"].items()}}


# ---------------- consent wording ----------------
NEG_RE = re.compile(r"\b(not|don't|do not|never|no|stop|opt out|unsubscribe|without|prefer not)\b", re.I)
CONSENT_SCHEMA = {"type": "object", "required": ["ticked_means_consent", "confusing", "reason"], "properties": {
    "ticked_means_consent": {"type": "boolean"}, "confusing": {"type": "boolean"}, "reason": {"type": "string"}}}


def consent_tick_means_yes(label: str) -> dict:
    """Does ticking this box mean the user agrees to the optional thing? Also flags confusing wording."""
    negations = len(NEG_RE.findall(label))
    # Heuristic: an even number of negations reads as plain opt-in ("do not tick if you do not want" = tick to receive).
    parity = negations % 2 == 0
    result = {"negations": negations, "double_negative": negations >= 2, "by": "heuristic", "tick_means_yes": parity}
    if available():
        try:
            # Thinking is on for this task only: without it the model is itself fooled by double negatives.
            j = ask_json(
                "You audit consent checkboxes on a shopping site. Label: \"" + label + "\"\n"
                "ticked_means_consent: true if a TICKED box results in the user receiving or agreeing to the "
                "optional thing. Work through the negations step by step in `reason` before answering.\n"
                "confusing: true if the wording uses double negatives or otherwise misleading phrasing.",
                task="consent wording", schema=CONSENT_SCHEMA, think=True)
            result.update(tick_means_yes=bool(j["ticked_means_consent"]),
                          readers_disagree=bool(j["ticked_means_consent"]) != parity,
                          double_negative=result["double_negative"] or bool(j.get("confusing")),
                          reason=j.get("reason", ""), by=backend_name())
            return result
        except Exception:
            pass
    return result


# ---------------- confirm-shaming copy ----------------
SHAME_RE = re.compile(
    r"\b(i hate|i don'?t (care|want to save|like (saving|deals))|i prefer (paying|to pay)|i like paying|"
    r"i'?d rather pay|i'?m fine (paying|missing)|i don'?t need (help|to save)|no,? i'?m (not|too))", re.I)
SHAME_SCHEMA = {"type": "object", "required": ["confirm_shaming", "reason"], "properties": {
    "confirm_shaming": {"type": "boolean"}, "reason": {"type": "string"}}}


def is_confirm_shaming(text: str) -> dict:
    if available():
        try:
            j = ask_json(
                "You audit e-commerce UI copy for 'confirm shaming': wording on the option a shopper must click to "
                "DECLINE an offer that puts words in the shopper's mouth to make declining feel foolish, guilty or "
                "shameful. Examples of confirm shaming: 'No thanks, I don't like free stuff', 'I'd rather pay full "
                "price'. NOT confirm shaming: 'No thanks', 'Continue without protection', 'Skip', 'Not now'.\n"
                "This text appears as the decline option next to a paid offer: \"" + text + "\"",
                task="confirm-shaming wording", schema=SHAME_SCHEMA)
            return {"hit": bool(j["confirm_shaming"]), "reason": j.get("reason", ""), "by": backend_name()}
        except Exception:
            pass
    m = SHAME_RE.search(text)
    return {"hit": bool(m), "reason": f"guilt phrase '{m.group(0)}'" if m else "", "by": "lexicon"}


# ---------------- verifiable claims ----------------
CLAIM_SCHEMA = {"type": "object", "required": ["claims"], "properties": {"claims": {"type": "array", "items": {
    "type": "object", "required": ["kind", "quote"], "properties": {
        "kind": {"type": "string", "enum": ["countdown", "deadline_date", "stock_count", "demand", "other"]},
        "quote": {"type": "string"},
        "displayed_time": {"type": "string"},
        "units": {"type": "integer"}}}}}}


def extract_claims(text: str) -> list:
    """Ask the model for every checkable urgency/scarcity claim on the page. Each claim must quote the page
    verbatim; claims whose quote is not in the text are discarded (grounding check), so the model cannot
    invent evidence. Returns [] if no model is available."""
    if not available():
        return []
    j = ask_json(
        "Extract every factual urgency or scarcity claim a shopper could check from this page text. "
        "kind=countdown for a running timer (put the exact timer text, e.g. '14:58', in displayed_time); "
        "stock_count for a claimed number of units left (put the number in units); demand for claims like "
        "'20 people viewing'. quote must be copied verbatim from the page.\n\nPAGE TEXT:\n" + text[:4000],
        task="claim extraction", schema=CLAIM_SCHEMA)
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    page = norm(text)
    return [c for c in j.get("claims", []) if c.get("quote") and norm(c["quote"]) in page]
