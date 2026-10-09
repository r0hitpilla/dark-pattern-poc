# Intent-Divergence Testing — dark pattern detection POC

Detects India CCPA (Guidelines for Prevention and Regulation of Dark Patterns, 2023) dark patterns
**behaviourally**: it proves that an interface produces an outcome the user did not intend, instead of
recognising what a screen looks like.

Most CCPA categories are defined by *falsity* (false urgency), *divergence from intent* (basket sneaking,
drip pricing, trick questions) or *asymmetry* (subscription traps). None of these is visible on a single
screenshot, which is the limit of AidUI, UIGuard and screenshot-VLM approaches.

## Demo result (DGX Spark, everything local)

```
Pattern                  Harness(dark) Harness(clean) Lexical(dark) Lexical(clean) VLM(dark) VLM(clean)
false_urgency                  ✓             ·              ✓             FP           ✓         FP
false_scarcity                 ✓             ·              ✓             FP           ✓         FP
basket_sneaking                ✓             ·              ✓             ·            ✗         FP
drip_pricing                   ✓             ·              ✗             ·            ✓         FP
interface_interference         ✓             ·              ✓             ·            ✓         ·
confirm_shaming                ✓             ·              ✓             ·            ✓         ·
trick_question                 ✓             ·              ✓             ·            ✓         ·
subscription_trap              ✓             ·              ✗             ·            ✗         ·
nagging                        ✓             ·              ✗             ·            ✗         ·

Harness: 9/9 detected, 0 false alarms
Lexical baseline: 6/9 detected, 2 false alarms
VLM baseline (qwen3.5:35b-a3b): 6/9 detected, 4 false alarms
LLM navigator on Kartiq (dark): same end state as scripted careful persona; join/cancel 2/6 actions
LLM navigator on Kartiq (honest): same end state as scripted careful persona; join/cancel 2/2 actions
```

Two baselines, both deliberately *not* strawmen:

- **Lexical**: a single-screen recogniser that sees pre-ticked boxes, dominant buttons and double negatives.
- **Screenshot VLM**: a local 35B vision-language model shown each screen with the CCPA definitions, the
  approach most recent work takes. It reads copy well, but on the honest shop it flags the real deadline,
  the real stock count and the disclosed delivery fee, and hallucinates a pre-ticked consent box. It cannot
  tell true from false or disclosed from dripped, because those need a second screen, session or system of record.

## How local LLMs are used: the model proposes, the oracle disposes

| Task | What the model does | What keeps it honest |
|---|---|---|
| Navigation (`personas.Agent`) | A third persona drives the journey from the one-sentence intent alone, with no goal words or site hints. It also runs the join/cancel flows. | End state is read from the order and account system of record. A navigation mistake shows up as a failed journey, never a false finding. |
| Claim extraction (`checks.falsity`) | Finds urgency/scarcity claims however they are phrased | Quotes must appear verbatim on the page (grounding check). Deadline arithmetic and the inventory comparison are deterministic. |
| Consent wording | Works out what a tick means | Runs with thinking on: without it the model is itself fooled by the double negative. Disagreement with the negation-count rule is added to the evidence. |
| Confirm-shaming wording | Judges decline copy next to an offer | Marked “Judged”, for human review |
| VLM baseline (`vlm_baseline.py`) | Comparison only | Never used for a harness finding |

Prices, order contents, membership, consent state, inventory and click counts are always decided by
deterministic code. Every model call has a fallback (`DP_NO_LLM=1` still gives 9/9), screens never leave the
machine, and responses are cached in `.llm_cache/`, so reruns are fast and reproducible. The report lists
every call by task, with model time.

## Layout

```
shop/app.py          Kartiq, a fictional shop. --mode dark seeds 9 patterns; --mode clean is the honest control
harness/
  personas.py        careful vs hurried (bounded-attention) simulated users sharing one intent,
                     plus Agent: an LLM navigator driven only by the plain-English intent
  journey.py         runs a persona through checkout in a fresh session, records an evidence trace,
                     STOPS at the payment gate (never presses Pay)
  oracles.py         intent oracles → findings (Proven / Measured / Judged)
  checks.py          cross-session falsity, join-vs-cancel friction asymmetry, nagging
  baseline.py        single-screen recognition baseline for the side-by-side
  llm.py             local LLM layer (Ollama): model auto-pick, JSON schema, disk cache, call stats
  vlm_baseline.py    screenshot-VLM baseline (state-of-the-art comparison)
  report.py          self-contained HTML evidence report
run_demo.py          starts both shops, runs everything, scores, writes reports/
```

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python run_demo.py       # → reports/report.html, reports/findings.json  (~2.5 min cold, ~1 min cached)
```

The first installed model is picked automatically (`qwen3.5:35b-a3b`, then `gpt-oss:20b`, `qwen2.5:32b`, …).

| Env var | Effect |
|---|---|
| `DP_LLM_MODEL` / `DP_VLM_MODEL` | Force a text / vision model |
| `DP_NO_LLM=1` | Deterministic heuristics only, no model calls |
| `DP_NO_VLM=1` | Skip the screenshot-VLM baseline (the slow part, ~10 s per screen) |
| `DP_LLM_CACHE=0` | Ignore the response cache |
| `OLLAMA_HOST` | Default `http://localhost:11434` |

## The five techniques

| Technique | Catches | How |
|---|---|---|
| Intent oracles | basket sneaking, drip pricing | Persona with an explicit goal; order and price at the payment gate compared with intent and with the first price shown |
| Persona differential | interface interference, trick question | Careful and hurried personas share a goal; whatever the hurried one ends up with is the manipulation delta |
| Falsity verification | false urgency / scarcity | Fresh sessions over time: a real deadline is the same moment for everyone; stock claim checked against inventory API |
| Friction asymmetry | subscription trap | Goal-directed agent counts actions to join vs cancel |
| Repetition | nagging | Counts reappearance of a dismissed prompt |

## Pointing it at a real target (UAT)

Edit `target()` in `run_demo.py`: product path, account/system-of-record page and keys, membership and
consent labels, optional inventory API, and the intent's goal/avoid words. Persona logic works on any DOM
(it reads the `<main>` region's controls, checkboxes and tables).

## Limits

- The hurried persona is a **risk indicator**, not a validated model of real shoppers. Calibrate against
  session data before quoting user harm.
- Run against **UAT/staging with test accounts**. Do not run authenticated journeys against third-party
  platforms without written permission.
- Findings are **evidence for legal review**, not legal conclusions.
- The scripted personas still use goal words. The LLM navigator removes that need and matched them on both
  shops here, but it is a 4-screen journey; longer real journeys will need more steps and a check on the trace.
  The scarcity check needs the client's inventory system of record.
- Model output varies between models and Ollama versions. qwen3.5 with `think: false` ignores Ollama's `format`,
  so the schema is also put in the prompt and replies are validated.
- 9/9 is on a shop built to test the harness. It shows the method works; it is not an accuracy claim on
  real platforms.
