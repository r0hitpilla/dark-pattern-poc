# Intent-Divergence Testing: dark pattern detection POC

Detects India CCPA (Guidelines for Prevention and Regulation of Dark Patterns, 2023) dark patterns
**behaviourally**: it shows that an interface produces an outcome the user did not intend, instead of
recognising what a screen looks like.

Most CCPA categories are defined by *falsity* (false urgency), *divergence from intent* (basket sneaking,
drip pricing, trick questions) or *asymmetry* (subscription traps). None of these is visible on a single
screenshot, which is the limit of screenshot and screen-recognition approaches.

The repo has two engines:

| | `idt/` generic engine (v2) | `harness/` scripted engine (v1) |
|---|---|---|
| Input | a URL | a URL plus per-site config (paths, labels, goal words) |
| Navigation | local LLM agents from a plain-English goal | keyword-scripted personas |
| Categories | all 13 CCPA categories | 9 |
| Run | `python audit.py <url>` · `python bench.py` | `python run_demo.py` |

## Generic engine (`idt/`): give it a URL

```
URL ─► discover ─► walk ─────────────► probe ─────────────► judge ─► report
       pages,      careful + hurried    fresh sessions,       13 CCPA
       product,    users, same goal,    quantity test,        comparisons
       paid plan   stop before paying   cookie refusal, ...
```

1. **Discover** (`discover.py`) reads the home page, visits the pages that matter, and picks the most promoted
   product (from the site's product cards) and any paid plan. Journey types are fixed and generic: buy one
   item; join and cancel a plan.
2. **Walk** (`journey.py`, `agent.py`). A *careful* LLM agent declines everything it did not ask for; its
   action log is the record of what the user chose. A *hurried* user fills only what it must, never changes a
   preset option, and clicks the most visually dominant control, where salience is computed from the DOM, not
   chosen by the model. A payment guard never presses Pay.
3. **Probe** (`probes.py`). The page is reopened in fresh sessions over time, since a real deadline is the same
   moment for everyone. The engine tries to buy more than the "only N left". It counts the actions to refuse
   cookies vs to accept them. It flags result cards that link to ad URLs without an ad label. It watches for
   downloads, redirects and new windows the user did not ask for.
4. **Judge** (`oracles.py`). Each category is a comparison that holds on any site:

| CCPA category | Comparison | Strength |
|---|---|---|
| False urgency | implied countdown deadline across fresh sessions | Proven |
| False urgency (scarcity) | basket accepted more than "only N left" | Proven |
| Basket sneaking | paid line in the basket vs the user's own choices | Proven |
| Drip pricing | final total vs first price + charges shown with it (must add up) | Proven / Measured |
| Bait and switch | price on the clicked listing card vs the product page | Proven |
| Interface interference | careful vs hurried outcome; accept vs refuse effort for cookies | Proven / Measured |
| Forced action | the site refused to continue without an unrelated step | Proven |
| Subscription trap | join vs cancel effort; offline-only cancellation | Proven / Measured |
| SaaS billing | recurring price stated before vs only after signing up | Proven |
| Nagging | dismissed popup reappears on later screens | Measured |
| Disguised ads | unlabelled result card links to an ad/advertiser URL | Measured |
| Rogue malware | download started without being asked; fake system warning | Proven / Judged |
| Confirm shaming | decline/leave wording | Judged |
| Trick question | consent wording (model with reasoning) + pre-set default | Measured / Judged |

**The model proposes, fixed code decides.** The local LLM reads screens: what a control does, which line is
a fee, what a claim says. Every fact a verdict rests on is grounded. Amounts must appear verbatim on the page
and are parsed by code, quotes must be found on the page, element ids must exist, and control states are read
from the DOM. `idt/` contains no site names, routes or labels.

### Benchmark

Three structurally different test shops, each with a dark and an honest version, given only their URL:

| Shop | How it differs | Seeded (dark version) |
|---|---|---|
| Kartiq (`shop/app.py`) | ₹, tables, `role=dialog` nag, membership | false urgency & scarcity, basket sneaking, drip pricing, interface interference, confirm shaming, trick question, subscription trap, nagging |
| Brewbox (`shops/brewbox.py`) | $, no landmarks, div rows, cookie banner, custom popup, account checkout, card form | cookie interface interference, forced action, drip pricing, SaaS billing, subscription trap, nagging |
| Voltaro (`shops/voltaro.py`) | `49,00 €`, search grid, sponsored results, radio consent | bait and switch, disguised ads, rogue malware, false scarcity, basket sneaking, trick question |

Result (same code, zero site config, qwen3.5:35b-a3b on a DGX Spark, ~25 min cold):

```
Kartiq  (dark)    9/9 found    Kartiq  (honest)   0 false alarms
Brewbox (dark)    6/6 found    Brewbox (honest)   0 false alarms
Voltaro (dark)    6/6 found    Voltaro (honest)   0 false alarms
Total: 21/21 seeded patterns, all 13 CCPA categories, 0 false alarms
```

Read-only runs on real public test-automation shops (no ground truth; no findings is the expected answer):

| Site | Careful user got to | Findings |
|---|---|---|
| demoblaze.com | cart, stopped at "Place Order" | none |
| sauce-demo.myshopify.com | Shopify checkout, stopped at "Pay now" | none (VAT "including taxes" correctly not flagged) |
| practicesoftwaretesting.com | product added; checkout needs login (read-only boundary) | none |
| automationexercise.com | stalled on the "added to cart" modal | none |

The real-site runs found and fixed two false alarms during development: UK VAT shown at checkout read as drip
pricing, and a hurried user's own wandering read as basket sneaking.

### Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python bench.py                  # 3 shops × {dark, honest}; ~20–35 min cold on a DGX Spark
.venv/bin/python bench.py --real           # + read-only audits of public test-automation shops
.venv/bin/python audit.py https://staging.example/            # audit any site you are authorised to test
.venv/bin/python audit.py --readonly https://public.example/  # no accounts, no personal data, no subscriptions
```

Output is `reports/idt_report.html` (evidence report with screenshots) and `reports/idt_findings.json`.

## Scripted engine (`harness/`, v1)

The original POC: one shop, scripted personas, plus two single-screen baselines for comparison (lexical, and a
screenshot VLM). Run `python run_demo.py`; see `reports/report.html`. It showed the method: harness 9/9 with 0
false alarms; lexical baseline 6/9 with 2; screenshot VLM (qwen3.5:35b-a3b) 6/9 with 4. The baselines flag the
honest shop's real deadline and disclosed fee because they cannot compare screens, sessions or a system of record.

## Local LLM

Ollama, everything on this machine. The first installed model is used (`qwen3.5:35b-a3b`, then `gpt-oss:20b`,
`qwen2.5:32b`, …). Responses are cached in `.llm_cache/`. Thinking is turned on only where it changes the
answer: consent wording (double negatives fool the model otherwise) and the step after a site refuses an
attempt.

| Env var | Effect |
|---|---|
| `DP_LLM_MODEL` / `DP_VLM_MODEL` | Force a text / vision model |
| `DP_NO_LLM=1` | v1 only: deterministic heuristics, no model calls |
| `DP_NO_VLM=1` | v1 only: skip the screenshot-VLM baseline |
| `DP_LLM_CACHE=0` | Ignore the response cache |

## Limits

- **The test shops were written alongside the engine.** They differ in structure, wording, currency and
  mechanism, and `idt/` never names them, but they are not independent of it. Real-site runs are the check.
- **Real-site navigation is the weak point.** See the benchmark section for how far each read-only journey got.
  Unusual widgets (in-page "added to cart" modals, accordions, login-gated checkouts) can stall the agent.
  A stalled journey produces no finding, not a false one.
- Without a site's back end, stock and deadline claims are tested from outside (quantity probe, fresh sessions).
  An inventory feed in UAT makes these checks stronger.
- The hurried user is a **risk indicator**, not a validated model of real shoppers.
- Run full audits only against **UAT/staging with test accounts** or sites you are authorised to test. Journeys
  always stop before payment. Findings are **evidence for legal review**, not legal conclusions.
