"""Two simulated users who share one goal and differ only in attention.

careful : reads every option, unticks optional paid extras and consents its intent
          declines, and picks the button whose words match its goal.
hurried : bounded attention. Never touches checkboxes, reads nothing, and clicks the
          most visually dominant control on the screen.

If both reach the same end state, the interface is honest about the goal. If the hurried
user ends up with more than the careful one, the difference is what the interface takes
from inattentive users: the manipulation delta.

The hurried persona is a risk indicator, not a validated model of real shoppers; it should
be calibrated against human session data before being quoted as user harm.
"""
from dataclasses import dataclass, field

from . import llm

PAID_RE_WORDS = ("₹", "add ", "cover", "protect", "insurance", "warranty", "gift wrap", "donate")
DECLINE_WORDS = ("no thanks", "without", "skip", "not now", "continue without", "no, thanks", "decline")


@dataclass
class Intent:
    goal_words: dict                      # word -> weight; what moving towards the goal looks like
    avoid_words: tuple = ()               # offers this user does not want
    decline_optional: bool = True         # untick optional paid extras and consents
    description: str = ""


@dataclass
class Decision:
    checkbox_changes: list = field(default_factory=list)   # (idx, value, reason)
    radio: list = field(default_factory=list)               # radio group names to answer
    click: int | None = None
    click_reason: str = ""
    notes: list = field(default_factory=list)               # structural observations (e.g. pre-ticked paid option)


def _score(text: str, intent: Intent, page_has_offer: bool) -> float:
    t = text.lower()
    s = sum(w for k, w in intent.goal_words.items() if k in t)
    s -= 3 * sum(1 for k in intent.avoid_words if k in t)
    if page_has_offer and any(k in t for k in DECLINE_WORDS):
        s += 1.5
    return s


class Careful:
    name = "careful"

    def decide(self, obs: dict, intent: Intent) -> Decision:
        d = Decision()
        for cb in obs["checkboxes"]:
            label = cb["label"]
            low = label.lower()
            paid = any(k in low for k in PAID_RE_WORDS)
            if paid:
                if cb["checked"]:
                    d.notes.append({"type": "pre_ticked_paid_option", "label": label})
                if intent.decline_optional:
                    d.checkbox_changes.append((cb["idx"], False, "optional paid extra not in intent"))
                continue
            # treat as a consent box: work out what a tick means before deciding
            c = llm.consent_tick_means_yes(label)
            want = not intent.decline_optional
            target = want if c["tick_means_yes"] else not want
            d.notes.append({"type": "consent_box", "label": label, "pre_ticked": cb["checked"], **c,
                            "set_to": target})
            d.checkbox_changes.append((cb["idx"], target, "consent set per intent"))
        for r in obs["radios"]:
            if r["required"]:
                d.radio.append(r["name"])
        texts = " ".join(c["text"].lower() for c in obs["candidates"])
        has_offer = any(k in texts for k in intent.avoid_words)
        ranked = sorted(obs["candidates"], key=lambda c: (_score(c["text"], intent, has_offer), c["salience"]),
                        reverse=True)
        if ranked and _score(ranked[0]["text"], intent, has_offer) > 0:
            d.click = ranked[0]["idx"]
            d.click_reason = f"best match for goal ('{ranked[0]['text']}')"
        return d


class Hurried:
    name = "hurried"

    def decide(self, obs: dict, intent: Intent) -> Decision:
        d = Decision()
        for r in obs["radios"]:          # answers required questions just to get past them
            if r["required"]:
                d.radio.append(r["name"])
        if obs["candidates"]:
            top = max(obs["candidates"], key=lambda c: c["salience"])
            d.click = top["idx"]
            d.click_reason = f"most visually dominant control ('{top['text']}', salience {top['salience']})"
        return d


AGENT_SCHEMA = {"type": "object", "required": ["checkboxes", "click", "reason"], "properties": {
    "checkboxes": {"type": "array", "items": {"type": "object", "required": ["idx", "checked"], "properties": {
        "idx": {"type": "integer"}, "checked": {"type": "boolean"}, "why": {"type": "string"}}}},
    "click": {"type": "integer"}, "reason": {"type": "string"}}}


class Agent:
    """Careful user driven by a local LLM. It gets only the plain-English intent: no goal words, no avoid
    words, no site-specific hints. That is what lets the harness run on a site nobody has scripted.

    The agent only chooses actions. What it ended up with is still read from the order and the account
    system of record by the deterministic oracles, so a navigation mistake shows up as a failed journey,
    never as a false finding."""
    name = "agent"

    def __init__(self):
        self.history = []

    def decide(self, obs: dict, intent: Intent) -> Decision:
        d = Decision()
        for r in obs["radios"]:
            if r["required"]:
                d.radio.append(r["name"])
        if not obs["candidates"]:
            return d
        ctrls = "\n".join(f"[{c['idx']}] {c['text']!r}" for c in obs["candidates"])
        boxes = "\n".join(f"[{b['idx']}] {'TICKED' if b['checked'] else 'unticked'}: {b['label']!r}"
                          for b in obs["checkboxes"]) or "(none)"
        hist = "\n".join(self.history[-6:]) or "(start)"
        prompt = (
            f"You are a careful online shopper. YOUR GOAL: {intent.description}\n"
            "Read every option. Make each checkbox match your goal (untick anything you did not ask for; read "
            "consent wording carefully, including negations). Decline offers, upgrades and trials you did not "
            "ask for. Then click the one control that moves you towards your goal. If you are already done or "
            "no control helps, click -1. A payment button is handled for you; never choose one.\n\n"
            f"SCREEN {obs['url']}\nPAGE TEXT:\n{obs['text'][:1800]}\n\nCHECKBOXES:\n{boxes}\n\n"
            f"CLICKABLE CONTROLS:\n{ctrls}\n\nYOUR STEPS SO FAR:\n{hist}\n\n"
            "Answer with the checkbox states you want, the idx to click, and a reason of at most 20 words.")
        try:
            j = llm.ask_json(prompt, task="navigation", schema=AGENT_SCHEMA)
            if not any(c["idx"] == j.get("click") for c in obs["candidates"]):
                # Journeys only call decide() before the goal is reached, so "no control" is a slip: ask once more.
                j = llm.ask_json(prompt + f"\n\nYour previous answer said {j.get('reason', '')!r} but chose idx "
                                 f"{j.get('click')}, which is not a control. Your goal is not complete yet. Pick the "
                                 "idx from CLICKABLE CONTROLS that moves you towards it.",
                                 task="navigation", schema=AGENT_SCHEMA)
        except Exception as e:
            d.click_reason = f"LLM unavailable ({type(e).__name__})"
            return d
        valid_boxes = {b["idx"]: b for b in obs["checkboxes"]}
        for c in j.get("checkboxes", []):
            if c.get("idx") in valid_boxes:
                d.checkbox_changes.append((c["idx"], bool(c["checked"]), c.get("why") or "LLM: per intent"))
        click = j.get("click", -1)
        chosen = next((c for c in obs["candidates"] if c["idx"] == click), None)
        if chosen:
            d.click = click
            d.click_reason = f"LLM: {j.get('reason', '')}"
            self.history.append(f"{obs['url']}: clicked {chosen['text']!r}")
        else:
            d.click_reason = f"LLM chose no control: {j.get('reason', '')}"
        return d
