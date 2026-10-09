"""Single-screen recognition baseline.

Stands in for the current state of the art (AidUI, UIGuard, a VLM judging one screenshot):
it looks at each screen on its own and flags what that screen *looks like*. It is given
the same screens the harness visited, and it is deliberately not a strawman — it can see
pre-ticked boxes, dominant buttons and double negatives, as a good screenshot model can.

What it structurally cannot do is compare screens, sessions or flows, so it cannot tell a
true deadline from a fake one, a disclosed fee from a dripped one, or a fair cancel flow
from a trap.
"""
import re

from . import llm

URGENCY_RE = re.compile(r"ends in|hurry|limited time|deal ends|offer expires|\b\d{1,2}:\d{2}\b", re.I)
SCARCITY_RE = re.compile(r"only \d+ left|few left|selling fast|almost gone", re.I)
OFFER_WORDS = ("trial", "plus", "premium", "subscribe", "membership")


def recognise(screens):
    hits = {}

    def add(key, url, why):
        hits.setdefault(key, []).append(f"{url}: {why}")

    for s in screens:
        text, url = s.get("text", ""), s["url"]
        if URGENCY_RE.search(text):
            add("false_urgency", url, f"urgency language '{URGENCY_RE.search(text).group(0)}'")
        if SCARCITY_RE.search(text):
            add("false_scarcity", url, f"scarcity language '{SCARCITY_RE.search(text).group(0)}'")
        for cb in s.get("checkboxes", []):
            if cb["checked"] and "₹" in cb["label"]:
                add("basket_sneaking", url, f"pre-ticked paid option '{cb['label']}'")
            if llm.NEG_RE.findall(cb["label"]).__len__() >= 2:
                add("trick_question", url, f"double negative in '{cb['label']}'")
        cands = s.get("candidates", [])
        for c in cands:
            if llm.SHAME_RE.search(c["text"]):
                add("confirm_shaming", url, f"guilt wording '{c['text']}'")
            if any(w in c["text"].lower() for w in OFFER_WORDS):
                others = [o["salience"] for o in cands if o is not c]
                if others and c["salience"] > 4 * max(others):
                    add("interface_interference", url, f"offer button '{c['text']}' dominates the screen")
    return {k: sorted(set(v)) for k, v in hits.items()}
