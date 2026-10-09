"""Turn journey results and cross-session checks into findings.

Each finding states what the user intended, what actually happened, and how strong the
evidence is:
  Proven   : a deterministic oracle compared end state with intent or a system of record
  Measured : a counted quantity (clicks, reappearances) crossed a threshold
  Judged   : a wording judgement (local LLM if available, else lexicon) — needs human review
"""
import re

from . import llm
from .browser import rupees

CCPA = {
    "false_urgency": "False Urgency",
    "false_scarcity": "False Urgency (false scarcity claim)",
    "basket_sneaking": "Basket Sneaking",
    "drip_pricing": "Drip Pricing",
    "interface_interference": "Interface Interference",
    "confirm_shaming": "Confirm Shaming",
    "trick_question": "Trick Question",
    "subscription_trap": "Subscription Trap",
    "nagging": "Nagging",
}
FEE_RE = re.compile(r"fee|charge|handling|delivery|shipping|platform|convenience|tax|gst", re.I)
MONTHLY_RE = re.compile(r"₹\s?([\d,]+)\s*/\s*month", re.I)


def classify_rows(rows, product_name):
    out = {"product": [], "fees": [], "addons": [], "total": None}
    for label, val in ((r[0], r[1]) for r in rows):
        amt = rupees(val)
        if "total" in label.lower():
            out["total"] = amt
        elif product_name.lower() in label.lower() or "×" in label:
            out["product"].append((label, amt))
        elif FEE_RE.search(label):
            out["fees"].append((label, amt))
        else:
            out["addons"].append((label, amt))
    return out


def _finding(key, strength, title, expected, observed, evidence, shots=(), method=""):
    return {"key": key, "ccpa": CCPA[key], "strength": strength, "title": title, "expected": expected,
            "observed": observed, "evidence": evidence, "shots": [s for s in shots if s], "method": method}


def _step_shot(res, pred):
    for st in res["trace"]:
        if pred(st):
            return st["shot"]
    return None


def evaluate(cfg, journeys, fals, fric, nag):
    """Returns (findings, passes, delta)."""
    findings, passes = [], []
    by = {j["persona"]: j for j in journeys}
    careful, hurried = by["careful"], by["hurried"]
    pname, intent = cfg["product_name"], cfg["intent"]
    member_none, mkey, ckey = cfg["member_none"], cfg["member_key"], cfg["consent_key"]
    cls = {p: classify_rows(j["gate_rows"], pname) for p, j in by.items()}

    # ---------- basket sneaking ----------
    pre_ticked = [n for n in careful["notes"] if n["type"] == "pre_ticked_paid_option"]
    sneaked = {p: c["addons"] for p, c in cls.items() if c["addons"]}
    if pre_ticked or sneaked:
        ev = [f"Paid option pre-ticked on {n['url']}: \"{n['label']}\"" for n in pre_ticked]
        ev += [f"{p} user's order at the payment gate contains unrequested "
               + ", ".join(f"{l} (₹{a})" for l, a in items) for p, items in sneaked.items()]
        findings.append(_finding(
            "basket_sneaking", "Proven" if sneaked else "Measured",
            "Paid add-on lands in the basket unless the user notices and unticks it",
            f"Intent: {intent} — only the product in the order",
            "; ".join(f"{p}: {', '.join(l for l, _ in items)}" for p, items in sneaked.items()) or "pre-ticked paid option",
            ev, [_step_shot(careful, lambda s: s.get("checkboxes")), _step_shot(hurried, lambda s: "STOP" in s["action"])],
            "Intent oracle: order contents at payment gate vs stated intent"))
    else:
        passes.append("No unrequested items in either persona's order; no paid option pre-ticked.")

    # ---------- drip pricing ----------
    fs = careful["first_seen"] or {}
    disclosed = fs.get("disclosed_fees", [])
    qty = 1
    expected_payable = (fs.get("price") or 0) * qty + sum(f["amount"] for f in disclosed)
    undisclosed = [(l, a) for l, a in cls["careful"]["fees"]
                   if not any(d["label"] in l.lower() or l.lower() in d["label"] for d in disclosed if d["amount"] == a)]
    if undisclosed:
        extra = sum(a for _, a in undisclosed)
        findings.append(_finding(
            "drip_pricing", "Proven",
            f"₹{extra} in fees appear only at the final step",
            f"First price shown: ₹{fs.get('price')}"
            + (f" + {', '.join(f'₹{d['amount']} {d['label']}' for d in disclosed)}" if disclosed else "")
            + f" → expected payable ₹{expected_payable}",
            f"Careful user's payable at gate: ₹{careful['payable']} (+₹{careful['payable'] - expected_payable})",
            [f"Undisclosed on product page: {l} ₹{a}" for l, a in undisclosed],
            [careful["trace"][0]["shot"], _step_shot(careful, lambda s: "STOP" in s["action"])],
            "Price-consistency oracle: first displayed price vs final payable, after removing intended items"))
    else:
        passes.append(f"Final payable (₹{careful['payable']}) matches the price and fees shown on the first screen.")

    # ---------- unintended subscription / interface interference ----------
    subs = {p: j["account"].get(mkey, member_none) != member_none for p, j in by.items()}
    delta = {
        "payable": {p: j["payable"] for p, j in by.items()},
        "addons": {p: ", ".join(l for l, _ in cls[p]["addons"]) or "none" for p in by},
        "membership": {p: j["account"].get(mkey) for p, j in by.items()},
        "consent": {p: j["account"].get(ckey) for p, j in by.items()},
        "recurring": {p: (f"₹{MONTHLY_RE.search(j['gate_text']).group(1)}/month"
                          if subs[p] and MONTHLY_RE.search(j["gate_text"]) else "none") for p, j in by.items()},
    }
    if subs["hurried"] or subs["careful"]:
        hstep = next((s for s in hurried["trace"] if s.get("clicked") and
                      any(w in s["clicked"]["text"].lower() for w in cfg["avoid_words"])), None)
        ev, ratio_txt = [], ""
        if hstep:
            cstep = next((s for s in careful["trace"] if s["url"] == hstep["url"] and s.get("clicked")), None)
            if cstep:
                ratio = hstep["clicked"]["salience"] / max(cstep["clicked"]["salience"], 1)
                ratio_txt = f"{ratio:.0f}× more visually dominant"
                ev.append(f"On {hstep['url']} the offer button \"{hstep['clicked']['text']}\" is {ratio_txt} "
                          f"than the plain option \"{cstep['clicked']['text']}\" (area × colour × font).")
        ev.append("Careful user: " + delta["membership"]["careful"] + "; hurried user: " + delta["membership"]["hurried"])
        findings.append(_finding(
            "interface_interference", "Proven",
            "Inattentive user is steered into a paid subscription" if not subs["careful"]
            else "Both personas end up subscribed despite not intending to",
            f"Intent: {intent} — no subscription",
            f"Hurried user ends with {delta['membership']['hurried']} ({delta['recurring']['hurried']} after trial)",
            ev, [hstep["shot"] if hstep else None],
            "Persona differential: same goal, careful vs hurried; end state read from account system of record"))
    else:
        passes.append("Neither persona was enrolled in a subscription.")

    # ---------- trick question (consent) ----------
    cnotes = [n for n in careful["notes"] if n["type"] == "consent_box"]
    on = {p: j["account"].get(ckey) == "On" for p, j in by.items()}
    tricky = [n for n in cnotes if n.get("double_negative")]
    if tricky and any(on.values()):
        n = tricky[0]
        findings.append(_finding(
            "trick_question", "Proven",
            "Confusingly worded, pre-ticked consent leaves data sharing on",
            f"Intent: decline optional consents → {ckey}: Off",
            ", ".join(f"{p}: {ckey} {'On' if v else 'Off'}" for p, v in on.items()),
            [f"Label on {n['url']}: \"{n['label']}\"", f"{n['negations']} negations; pre-ticked: {n['pre_ticked']}",
             f"Wording assessed by: {n['by']}" + (f" — {n['reason']}" if n.get("reason") else "")]
            + (["The local LLM and the negation-count rule read this label differently: two careful readers "
                "disagree on what a tick means"] if n.get("readers_disagree") else []),
            [_step_shot(careful, lambda s: any(c for c in s.get("checkboxes", []) if c["label"] == n["label"]))],
            "Consent oracle (account state vs intent) + wording analysis"))
    elif any(on.values()):
        passes.append("Consent ended On without confusing wording — review manually.")
    else:
        passes.append("Optional consent ended Off for both personas; wording is plain.")

    # ---------- confirm shaming ----------
    seen, hits = set(), []
    for j in journeys:
        for st in j["trace"]:
            cands = st.get("candidates", [])
            if not any(w in c["text"].lower() for c in cands for w in cfg["avoid_words"]):
                continue
            for c in cands:
                t = c["text"]
                if t in seen or any(w in t.lower() for w in cfg["avoid_words"]):
                    continue
                seen.add(t)
                r = llm.is_confirm_shaming(t)
                if r["hit"]:
                    hits.append((st, t, r))
    if hits:
        st, t, r = hits[0]
        findings.append(_finding(
            "confirm_shaming", "Judged", "Declining the offer is worded to shame the user",
            "Neutral decline wording (e.g. 'No thanks')", f"\"{t}\"",
            [f"On {st['url']}: {r['reason']} (assessed by: {r['by']})"], [st["shot"]],
            "Wording judgement on decline options shown next to an offer — confirm with human review"))
    else:
        passes.append("Decline options next to offers use neutral wording.")

    # ---------- falsity ----------
    if fals["timer"]:
        if fals["timer"]["verdict"] == "false":
            findings.append(_finding(
                "false_urgency", "Proven", "Countdown restarts for every visitor",
                "A sale deadline is the same moment for every shopper",
                fals["timer"]["explanation"],
                [f"Session {o['session']}: showed {o['timer']}" for o in fals["observations"]],
                [fals["observations"][0]["shot"]], "Cross-session temporal consistency check"))
        else:
            passes.append("Urgency claim is genuine: " + fals["timer"]["explanation"])
    if fals["stock"]:
        if fals["stock"]["verdict"] == "false":
            findings.append(_finding(
                "false_scarcity", "Proven", "Low-stock claim contradicts inventory",
                f"Stock claim equals units available", fals["stock"]["explanation"],
                [f"Claim was identical in all {len(fals['observations'])} sessions"],
                [fals["observations"][0]["shot"]], "Claim vs client inventory system of record (UAT API)"))
        elif fals["stock"]["verdict"] == "consistent":
            passes.append("Scarcity claim is genuine: " + fals["stock"]["explanation"])
        else:
            passes.append("Scarcity claim unverified — no inventory oracle configured.")

    # ---------- subscription trap ----------
    if fric["verdict"] == "asymmetric":
        extras = []
        if any("answer" in p for p in fric["cancel"]["path"]):
            extras.append("mandatory exit survey")
        if any("continue cancelling" in p.lower() for p in fric["cancel"]["path"]):
            extras.append("retention-offer interstitial with a dominant 'keep' button")
        findings.append(_finding(
            "subscription_trap", "Measured",
            f"Cancelling takes {fric['ratio']:.0f}× the effort of joining",
            "Leaving is about as easy as joining (ratio ≤ 1.5)",
            f"Join: {fric['join']['actions']} actions · Cancel: {fric['cancel']['actions']} actions "
            f"across {fric['cancel']['screens']} screens",
            ["Cancel path: " + " → ".join(fric["cancel"]["path"])] + ([f"Includes {', '.join(extras)}"] if extras else []),
            [], "Friction asymmetry: goal-directed agent counts actions for join vs cancel"))
    else:
        passes.append(f"Join and cancel take similar effort ({fric['join']['actions']} vs {fric['cancel']['actions']} actions).")

    # ---------- nagging ----------
    if nag["verdict"] == "nagging":
        findings.append(_finding(
            "nagging", "Measured", "Dismissed prompt keeps coming back",
            "Once dismissed, the prompt stays dismissed for the session",
            f"Reappeared on {len(nag['reappeared_on'])} of {nag['pages_after_dismissal']} pages after 'Not now'",
            [f"Reappeared on: {', '.join(nag['reappeared_on'])}"], [nag["shot"]],
            "Repetition count across page loads after dismissal"))
    else:
        passes.append("App prompt respects dismissal.")

    if delta["payable"]["careful"] == delta["payable"]["hurried"] and not any(subs.values()) and not any(on.values()):
        passes.append("Careful and hurried personas reached identical outcomes (zero manipulation delta).")
    return findings, passes, delta
