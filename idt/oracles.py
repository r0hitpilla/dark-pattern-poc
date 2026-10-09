"""Site-agnostic oracles: each CCPA category is a comparison that holds on any website.

The inputs are journeys and probes whose facts are grounded (amounts parsed from verbatim page text, quotes
found on the page, element states read from the DOM, events seen by the browser). The model's only direct say
is in wording judgements, which are reported as "Judged".

Strength: Proven   = the site contradicted itself or the user's choices (UI vs UI, choice vs outcome)
          Measured = a counted or computed quantity crossed a threshold
          Judged   = wording judgement by the local LLM; needs human review
"""
import re

from harness import llm
from .journey import final_prices

CCPA = {
    "false_urgency": "False Urgency", "false_scarcity": "False Urgency (false scarcity)", "basket_sneaking": "Basket Sneaking",
    "confirm_shaming": "Confirm Shaming", "forced_action": "Forced Action", "subscription_trap": "Subscription Trap",
    "interface_interference": "Interface Interference", "bait_and_switch": "Bait and Switch", "drip_pricing": "Drip Pricing",
    "disguised_ads": "Disguised Advertisement", "nagging": "Nagging", "trick_question": "Trick Question",
    "saas_billing": "SaaS Billing", "rogue_malware": "Rogue Malware",
}


BRAND = set()      # words in most page titles of the audited site (its name); ignored when matching labels


def toks(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2} - BRAND


def same(a, b, th=0.5):
    A, B = toks(a), toks(b)
    return bool(A and B) and len(A & B) / min(len(A), len(B)) >= th


def F(key, strength, title, expected, observed, evidence, shots=(), method=""):
    return {"key": key, "ccpa": CCPA[key], "strength": strength, "title": title, "expected": expected, "observed": observed,
            "evidence": [e for e in evidence if e], "shots": [s for s in shots if s][:2], "method": method}


def cur(p):
    return {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(p.get("currency"), p.get("currency", "") + " ")


def fmt(p):
    return f"{cur(p)}{p['amount']:g}"


def _gate(j):
    return next((r for r in reversed(j["trace"]) if r["prices"]), None)


def evaluate(a: dict) -> tuple[list, list]:
    fs, passes = [], []
    pc = (a.get("purchase") or {}).get("careful")
    ph = (a.get("purchase") or {}).get("hurried")
    sj = (a.get("subscription") or {}).get("join")
    sc = (a.get("subscription") or {}).get("cancel")
    journeys = [j for j in (pc, ph, sj, sc) if j]
    titles = [{w for w in re.findall(r"[a-z0-9]+", r["title"].lower()) if len(w) > 2} for j in journeys for r in j["trace"]]
    BRAND.clear()
    if titles:
        counts = {}
        for t in titles:
            for w in t:
                counts[w] = counts.get(w, 0) + 1
        BRAND.update(w for w, c in counts.items() if c >= 0.6 * len(titles))

    # ---------------- basket sneaking: a paid line in the basket that the user never chose
    def sneaked(j):
        if not j:
            return []
        out = []
        item = (j["ledger"].get("item") or {}).get("label", "")
        for r in j["trace"]:
            if r["page_kind"] not in ("cart", "checkout", "order_review", "payment") and not r["actions"][0].startswith("STOP"):
                continue
            for p in r["prices"]:
                if not p.get("in_order", True):
                    continue
                # another product counts only for the careful user, who adds nothing but its target; a hurried user
                # can wander and add other products by its own click
                other = p["kind"] == "item" and item and not same(p["label"], item, 0.4) and j["persona"] == "careful"
                if p["kind"] == "addon" or other:
                    if p["amount"] > 0 and not any(same(p["label"], c, 0.4) for c in j["chose"]):
                        out.append((r, p))
        return out
    sc_c, sc_h = sneaked(pc), sneaked(ph)
    pre = [(r, d) for j in (pc,) if j for r in j["trace"] for d in r["defaults"]
           if d["checked"] and any(c["id"] == d["id"] and c["kind"] == "paid_addon" for c in r["ann"]["optional_choices"])]
    if sc_c or sc_h:
        r, p = (sc_c or sc_h)[0]
        who = "careful" if sc_c else "hurried"
        fs.append(F("basket_sneaking", "Proven", f"'{p['label']}' ({fmt(p)}) is added to the order without being chosen",
                    "Only the item the user selected is in the order",
                    f"{who} user's basket on {r['url']} contains '{p['label']}' {fmt(p)}; the user never selected it",
                    [f"Pre-selected on {pr['url']}: '{d['name']}'" for pr, d in pre[:2]] +
                    [f"{who} user's own choices on the journey: {', '.join(set((pc if sc_c else ph)['chose'])) or 'none'}"],
                    [r["shot"]] + [pr["shot"] for pr, _ in pre[:1]],
                    "Choice-vs-basket oracle: paid lines in the basket compared with the persona's positive choices"))
    elif pre:
        r, d = pre[0]
        fs.append(F("basket_sneaking", "Measured", "A paid extra is pre-selected", "Paid extras start unselected",
                    f"'{d['name']}' was ticked by default on {r['url']}", [], [r["shot"]], "Default-state audit"))
    elif pc:
        passes.append("No unchosen paid lines in the basket and no pre-selected paid extras.")

    # ---------------- drip pricing: final payable vs price first shown
    if pc and pc["ledger"].get("item"):
        first = pc["ledger"]["item"]
        prod = next((r for r in pc["trace"] if r["page_kind"] == "product"), None)
        disclosed = [p for p in (prod["prices"] if prod else []) if p["kind"] in ("fee", "shipping", "tax")]
        g = _gate(pc)
        lines = g["prices"] if g else []
        undisclosed = [p for p in lines if p["kind"] in ("fee", "shipping", "tax") and p["amount"] > 0
                       and not any(abs(d["amount"] - p["amount"]) < 0.01 for d in disclosed)]
        total = next((p for p in reversed(lines) if p["kind"] == "total"), None)
        if undisclosed and total:
            # the numbers must add up: a charge is only dripped if it raises the total above what was first shown
            qty = next((p.get("quantity") for p in lines if p["kind"] == "item" and p.get("quantity")), 1) or 1
            chosen_extra = sum(p["amount"] for p in lines if p["kind"] == "addon" and any(same(p["label"], c, 0.4) for c in pc["chose"]))
            expected = first["amount"] * qty + sum(d["amount"] for d in disclosed) + chosen_extra \
                - sum(p["amount"] for p in lines if p["kind"] == "discount")
            if total["amount"] <= expected + 0.01:
                undisclosed = []      # e.g. "including taxes £9.17": shown at checkout but already inside the price
        if undisclosed:
            fees = [p for p in undisclosed if p["kind"] == "fee"]
            fs.append(F("drip_pricing", "Proven" if fees else "Measured",
                        f"{cur(first)}{sum(p['amount'] for p in undisclosed):g} in charges appear only at {g['page_kind'].replace('_', ' ')}",
                        f"Price first shown: {fmt(first)}" + (f" + {', '.join(d['label'] + ' ' + fmt(d) for d in disclosed)}" if disclosed else "")
                        + " — every mandatory charge visible up front",
                        f"At {g['url']}: " + ", ".join(f"{p['label']} {fmt(p)}" for p in undisclosed)
                        + (f"; total payable {fmt(total)}" if total else ""),
                        [f"Not shown on the product page: {p['label']} {fmt(p)} ({p['kind']})" for p in undisclosed],
                        [prod and prod["shot"], g["shot"]],
                        "Price-consistency oracle: every charge at the last priced step must have been shown with the first price"))
        elif g:
            passes.append(f"Every charge at the last priced step was shown with the first price ({fmt(first)}).")

    # ---------------- bait and switch: listing vs product page vs basket
    if pc and pc["ledger"].get("listing_card") and pc["ledger"].get("item"):
        lc, it = pc["ledger"]["listing_card"], pc["ledger"]["item"]
        if lc["price"] and lc["price"][1] == it["currency"] and it["amount"] > lc["price"][0] * 1.01:
            prod = next((r for r in pc["trace"] if r["page_kind"] == "product"), None)
            fs.append(F("bait_and_switch", "Proven", "Advertised price changes after the click",
                        f"Listing advertises '{lc['context'][:90]}'",
                        f"Product page charges {fmt(it)} for '{it['label']}'",
                        [f"Listing card: {lc['context'][:160]}"], [pc["trace"][0]["shot"], prod and prod["shot"]],
                        "Listing-vs-product oracle: the card the user clicked vs the page it led to"))
        else:
            passes.append("The product page price matches the listing the user clicked.")

    # ---------------- interface interference: same goal, different attention -> different outcome
    if pc and ph:
        fc, fh = final_prices(pc), final_prices(ph)
        tc = next((p for p in reversed(fc) if p["kind"] == "total"), None)
        th = next((p for p in reversed(fh) if p["kind"] == "total"), None)
        # differences caused by items nobody chose are basket sneaking; here only what the hurried user was steered into
        unchosen = {p["label"] for _, p in sc_h}
        extra = [p for p in fh if p["kind"] in ("addon", "recurring") and not any(same(p["label"], q["label"]) for q in fc)
                 and p["label"] not in unchosen]
        sub_h = a.get("membership", {}).get("hurried") == "yes" and a.get("membership", {}).get("careful") != "yes"
        gap = (th["amount"] - tc["amount"] - sum(p["amount"] for p in fh if p["label"] in unchosen and p["kind"] != "total")
               if tc and th else 0)
        if ph["chose"] and (extra or sub_h or gap > 0.01):
            ev, shots = [], []
            for r in ph["trace"]:
                offers = [r["ann"]["offers"], r["ann"]["declines"]]
                if offers[0] and offers[1]:
                    ev.append(f"On {r['url']} the offer and the decline compete; the hurried user clicked: {r['actions'][-1] if r['actions'] else '-'}")
                    shots.append(r["shot"])
                    break
            fs.append(F("interface_interference", "Proven", "A less attentive user ends up paying for more",
                        "Same goal → same outcome for careful and hurried users",
                        f"careful: {fmt(tc) if tc else '?'}; hurried: {fmt(th) if th else '?'}"
                        + (f"; hurried also has {', '.join(p['label'] + ' ' + fmt(p) for p in extra)}" if extra else "")
                        + ("; hurried user ends with an active membership" if sub_h else ""),
                        ev, shots, "Persona differential: careful vs hurried on one goal; outcome read from the basket"))
        else:
            passes.append("Careful and hurried users reached the same basket.")
    cs = a.get("consent")
    if cs:
        asym = cs.get("reject_actions") is not None and cs["accept_actions"] and cs["reject_actions"] > cs["accept_actions"] + 0.5
        if (cs.get("accept") and not cs.get("reject_first_layer")) or asym or not cs.get("refused_ok", True):
            fs.append(F("interface_interference", "Measured", "Refusing cookies is harder than accepting them",
                        "Refusing is as easy as accepting (same layer, similar prominence)",
                        f"Accept: {cs['accept_actions']} action ('{cs['accept']}'); refuse: "
                        + (f"{cs['reject_actions']} actions" if cs.get("reject_actions") is not None else "not achieved"),
                        [f"Refuse path: {' → '.join(cs.get('reject_path', [])[:6])}",
                         f"No refuse option on the first layer" if not cs.get("reject_first_layer") else
                         f"Accept is {cs['salience_ratio']}× as prominent as refuse" if cs.get("salience_ratio") else ""],
                        [cs.get("shot")], "Consent asymmetry probe: actions to accept vs to refuse, in fresh sessions"))
        else:
            passes.append(f"Cookie banner: refusing takes {cs.get('reject_actions')} action(s), same as accepting.")

    # ---------------- confirm shaming: decline wording (Judged)
    seen, hit = set(), None
    for j in journeys:
        for r in j["trace"]:
            for txt in r.get("decline_texts", []):
                if txt in seen:
                    continue
                seen.add(txt)
                v = llm.is_confirm_shaming(txt)
                if v["hit"] and not hit:
                    hit = (r, txt, v)
    if hit:
        r, t, v = hit
        fs.append(F("confirm_shaming", "Judged", "Declining is worded to shame the user", "Neutral decline wording",
                    f"\"{t}\" on {r['url']}", [f"{v['reason']} (assessed by {v['by']})"], [r["shot"]],
                    "Wording judgement on controls that decline an offer"))
    elif journeys:
        passes.append("Decline options use neutral wording.")

    # ---------------- trick question: confusing consent wording that defaults to consent
    tq = None
    for j in [x for x in (pc, ph, sj) if x]:
        for r in j["trace"]:
            for c in r["ann"]["optional_choices"]:
                if c["kind"] not in ("marketing_consent", "data_sharing", "newsletter", "auto_renew"):
                    continue
                d = next((x for x in r["defaults"] if x["id"] == c["id"]), None)
                if not d:
                    continue
                label = (f"{d['question']} — option: {d['name']}" if d["kind"] == "radio" and d.get("question") else d["name"])
                if label in seen:
                    continue
                seen.add(label)
                v = llm.consent_tick_means_yes(label)
                if v.get("double_negative") and not tq:
                    tq = (r, d, v, label)
    if tq:
        r, d, v, label = tq
        means = d["checked"] == v.get("tick_means_yes")
        fs.append(F("trick_question", "Measured" if (d["checked"] and means) else "Judged",
                    "Consent question is worded to confuse" + (" and is pre-set to consent" if d["checked"] and means else ""),
                    "A plain question; optional consent off by default",
                    f"\"{label[:200]}\" — {'selected' if d['checked'] else 'not selected'} by default",
                    [v.get("reason", "")[:300], f"Assessed by {v.get('by')}",
                     "The LLM and the negation-count rule disagree on what selecting it means" if v.get("readers_disagree") else ""],
                    [r["shot"]], "Consent wording analysis (local LLM with reasoning) + default-state audit"))
    elif journeys:
        passes.append("Consent questions are plainly worded.")

    # ---------------- forced action
    forced = []
    for j in [x for x in (pc, ph, sj) if x]:
        for r in j["trace"]:
            if r["ann"]["unrelated_requirements"] and (r.get("forced") or r.get("refused")):
                forced.append((r, r["ann"]["unrelated_requirements"][0]))
    cw = cs and cs.get("accept") and not cs.get("reject_first_layer") and cs.get("cover", 0) >= 0.5 and not cs.get("refused_ok")
    if forced or cw:
        if forced:
            r, req = forced[0]
            fs.append(F("forced_action", "Proven" if r.get("refused") else "Measured",
                        f"To continue, the user must {req['what'].lower()}", "Completing the task needs only what the task needs",
                        f"On {r['url']}: \"{req['quote'][:160]}\"",
                        [f"The site refused to continue: {'; '.join(r['refused'])}" if r.get("refused") else "",
                         f"Careful user: {r.get('forced')}" if r.get("forced") else ""],
                        [r["shot"]], "Careful user tries to proceed without the unrelated step; refusal recorded"))
        else:
            fs.append(F("forced_action", "Measured", "The site cannot be used without accepting tracking",
                        "Refusing optional cookies leaves the site usable", f"Banner covers {int(cs['cover'] * 100)}% with no refuse path",
                        [], [cs.get("shot")], "Consent probe"))
    elif journeys:
        passes.append("No unrelated step was required to complete the journeys.")

    # ---------------- subscription trap & SaaS billing
    if sj and sc:
        offline = any(r["ann"]["cancel_offline_only"] for r in sc["trace"])
        ok_c = sc["reached"] == "done" and a.get("membership", {}).get("after_cancel") == "no"
        ratio = sc["actions"] / max(sj["actions"], 1)
        if offline or not ok_c or ratio > 1.5:
            r = next((r for r in sc["trace"] if r["ann"]["cancel_offline_only"]), sc["trace"][-1])
            fs.append(F("subscription_trap", "Proven" if (offline or not ok_c) else "Measured",
                        "Cancelling is " + ("not possible online" if offline else "harder than joining" if ok_c else "not achievable"),
                        "Leaving is about as easy as joining (ratio ≤ 1.5) and possible online",
                        f"Join: {sj['actions']} actions. Cancel: {sc['actions']} actions, "
                        + ("cancelled" if ok_c else f"not cancelled ({sc['reached']})"),
                        ["Cancel path: " + " → ".join(x for rr in sc["trace"] for x in rr["actions"])[:600]],
                        [r["shot"]], "Friction asymmetry: same agent, join vs cancel, from the home page"))
        else:
            passes.append(f"Cancelling took {sc['actions']} actions vs {sj['actions']} to join.")
        # recurring terms disclosed before the commitment?
        post = a.get("recurring_after_join") or []
        commit = next((i for i, r in enumerate(sj["trace"]) if any(re.search(r"click .*(start|join|subscribe|trial|sign ?up|activate)", x, re.I)
                                                                     for x in r["actions"])), len(sj["trace"]) - 1)
        pre = sj["trace"][:commit + 1]
        pre_txt = " ".join(c["quote"] for r in pre for c in r["claims"] if c["kind"] == "recurring_terms")
        pre_amt = [p for r in pre for p in r["prices"] if p["kind"] == "recurring"]
        if post:
            p = post[0]
            told = any(abs(q["amount"] - p["amount"]) < 0.01 for q in pre_amt) or p["quote"] in pre_txt
            if not told:
                fs.append(F("saas_billing", "Proven", f"A recurring {fmt(p)} charge is revealed only after signing up",
                            "Recurring price and period are stated before the user commits",
                            f"After joining, the account shows '{p['label']}' {fmt(p)}" + (f" per {p['period']}" if p.get("period") else ""),
                            ["Before committing, the user saw: " + (pre_txt[:200] or "no recurring price")],
                            [sj["trace"][-1]["shot"]], "Disclosure oracle: recurring terms before vs after the commitment"))
            else:
                passes.append("Recurring price was stated before signing up.")

    # ---------------- nagging
    nag = [(s, urls) for j in journeys for s, urls in j["popup_returns"].items() if len(set(urls)) >= 2]
    if cs and cs.get("returns_after_refusal"):
        nag.append((cs["banner"][:60], ["cookie banner returned after refusal"]))
    if nag:
        s, urls = nag[0]
        fs.append(F("nagging", "Measured", "A dismissed popup keeps coming back", "Once dismissed, it stays dismissed",
                    f"Popup '{s}' reappeared on {len(set(urls))} later screens", [", ".join(sorted(set(urls)))[:300]], [],
                    "Repetition count of dismissed popups across the journey"))
    elif journeys:
        passes.append("Dismissed popups stayed dismissed.")

    # ---------------- false urgency / scarcity
    for t in a.get("temporal", []):
        if t.get("countdown", {}).get("verdict") == "moves":
            c = t["countdown"]
            fs.append(F("false_urgency", "Proven", "Countdown restarts for each visitor", "A deadline is the same moment for everyone",
                        f"Implied deadline moved {c['spread_s']:.0f}s across {len(c['seen'])} fresh sessions {c['elapsed_s']:.0f}s apart",
                        [f"Timers seen: {', '.join(x for x in c['seen'] if x)} on {t['url']}"],
                        [t["observations"][0]["shot"]], "Cross-session temporal consistency"))
            break
        if t.get("countdown"):
            passes.append(f"Countdown on {t['url']} points at one fixed deadline.")
    q = a.get("quantity")
    if q and q["verdict"] == "accepted_more":
        fs.append(F("false_scarcity", "Proven", f"'Only {q['claimed']} left', but the shop accepted {q['in_basket']}",
                    f"No more than {q['claimed']} can be bought", f"Basket holds {q['in_basket']} × '{q['quote']}'",
                    [f"Asked for {q['tried']}; no refusal" if not q["refused"] else f"Refusals: {q['refused']}"],
                    [r["shot"] for r in q["trace"][-1:]], "Quantity probe: try to buy more than the claimed stock"))
    elif q and q["verdict"] == "capped":
        passes.append(f"Stock claim held: the basket was capped at {q['in_basket']}.")

    # ---------------- disguised ads
    hid = [h for h in a.get("ads", []) if not h["labelled"]]
    if hid:
        h = hid[0]
        fs.append(F("disguised_ads", "Measured", "Advertiser links look like ordinary results",
                    "Paid placements are labelled as ads", f"Unlabelled card '{h['card'][:100]}' links to {h['href'][:120]}",
                    [f"{len(hid)} unlabelled ad-type link(s) on {h['page']}"], [], "Link-destination audit of result cards"))
    elif a.get("ads"):
        passes.append("Ad placements in results are labelled.")

    # ---------------- rogue malware
    ev = [e for j in journeys for e in j["events"]] + [e for j in a.get("extra_events", []) for e in j]
    dls = [e for e in ev if e["type"] == "download" and (not e["after_user_action"] or e["executable"])]
    fake = [(j, r) for j in journeys for r in j["trace"] if r["ann"]["fake_system_alert"]]
    if dls or fake:
        e = dls[0] if dls else None
        fs.append(F("rogue_malware", "Proven" if e and not e["after_user_action"] else "Judged",
                    "The site pushes a software download" if e else "The site imitates a system warning",
                    "A shop never starts downloads or imitates system warnings",
                    (f"Download of '{e['file']}' started on {e['page']} {'without being asked' if not e['after_user_action'] else ''}" if e else
                     f"On {fake[0][1]['url']}: {' / '.join(fake[0][1]['overlay_text'])[:200]}"),
                    ([f"{x['file']} from {x['url']}" for x in dls[:3]] +
                     [f"Fake system warning on {r['url']}" for _, r in fake[:1]]),
                    [fake[0][1]["shot"]] if fake else [], "Browser event monitor (downloads, new windows, redirects) + screen reading"))
    elif journeys:
        passes.append("No unrequested downloads, redirects or fake system warnings.")
    return fs, passes
