"""Walk one journey as one persona, recording an evidence trace. Stops before anything that would pay.

The trace keeps, per screen: what the page was, the prices and claims on it (grounded), the default state of
every option before the persona touched it, popups present, what the persona did and chose, attempts the site
refused, and anything the site did by itself (downloads, redirects, new windows).
"""
import re

from . import read, vision
from .perceive import Tab, PAY_RE, COMMIT_RE

ERROR_RE = re.compile(r"\b(required|must|please (enter|select|tick|check|accept|agree)|cannot|can't|invalid|error|you need to|to continue)\b", re.I)
PRICED_KINDS = {"product", "cart", "checkout", "payment", "order_review", "subscription_offer", "confirmation", "account"}
CLAIM_KINDS = {"home", "listing", "product", "subscription_offer", "cart"}


NATIVE_INVALID_JS = r"""(id) => { const b = document.querySelector('[data-idt="' + id + '"]'); const f = b && b.closest('form');
  if (!f) return []; return [...f.elements].filter(e => e.checkValidity && !e.checkValidity() && e.getBoundingClientRect().width > 0)
  .map(e => { const l = e.closest('label'); const n = (l ? l.innerText : (e.name || e.placeholder || 'field'))
  .replace(/\s+/g, ' ').trim().slice(0, 40); return n + ': ' + e.validationMessage; }); }"""


def sig(text: str) -> str:
    return read.norm(text)[:70]


def at_gate(snap) -> str | None:
    if snap["payment_fields"]:
        return "card-details form"
    for e in snap["elements"]:
        if e["kind"] in ("button", "link") and e["region"] != "nav" and PAY_RE.match(e["name"] or ""):
            return f"'{e['name']}'"
    return None


def run(browser, start_url: str, persona, *, readonly=False, max_steps=16, tab=None, keep_open=False, done_kinds=None) -> dict:
    """done_kinds: page kinds where the persona may declare the goal reached (None = anywhere)."""
    own = tab is None
    tab = tab or Tab(browser, start_url, readonly)
    tab.goto(start_url)
    trace, ledger, chose = [], {"item": None, "listing_card": None}, []
    stalled, rescued = None, 0       # stalled = name of the last click that changed nothing
    reached, n_events, dismissed = "max_steps", 0, {}
    budget, step = max_steps, -1
    while budget > 0 and step < max_steps * 2:
        step += 1
        snap = tab.snap()
        ann = read.annotate(snap)
        gate = at_gate(snap)
        kind = ann["page_kind"]
        rec = {"step": step, "url": snap["url"], "page_kind": kind, "title": snap["title"],
               "overlays": [sig(o["text"]) for o in snap["overlays"]], "overlay_text": [o["text"][:200] for o in snap["overlays"]],
               "prices": read.prices(snap) if (kind in PRICED_KINDS or gate) else [],
               "claims": read.claims(snap["text"]) if kind in CLAIM_KINDS else [],
               # every amount written on the screen, parsed by code (not by the model)
               "amounts": [a[0] for a in (read.money(m.group(0)) for m in read.MONEY_RE.finditer(snap["text"])) if a],
               "defaults": [{"id": e["id"], "name": e["name"], "question": e.get("question"), "kind": e["kind"], "checked": e["checked"]}
                            for e in snap["elements"] if e["checked"] is not None],
               "ann": ann, "shot": tab.shot(), "actions": [], "chose": [],
               "cards": [{"href": snap["by_id"][c["id"]]["href"], "offsite": snap["by_id"][c["id"]]["offsite"],
                          "card": snap["by_id"][c["id"]]["context"] or snap["by_id"][c["id"]]["name"], "labelled": c["labelled_as_ad"]}
                         for c in ann["product_cards"]],
               "decline_texts": [snap["by_id"][i]["name"] for i in ann["declines"] if snap["by_id"][i]["name"]] +
                                [snap["by_id"][p[f]]["name"] for p in ann["popups"] if p["kind"] != "cookie_consent"
                                 for f in ("reject_id", "dismiss_id") if p.get(f) and snap["by_id"][p[f]]["name"]]}
        if kind == "product" and ledger["item"] is None:
            ledger["item"] = next((dict(p) for p in rec["prices"] if p["kind"] == "item"), None)
            if ledger["item"] and ledger["listing_card"]:      # name it as the shopper saw it when choosing
                ledger["item"]["label"] = ledger["listing_card"]["name"] or ledger["item"]["label"]
        if gate:
            rec["actions"] = [f"STOP at payment gate ({gate}); never pressed"]
            trace.append(rec)
            reached = "gate"
            break
        try:
            try:
                acts, j = persona.decide(snap, ann)
            except Exception:
                acts, j = persona.decide(snap, ann)     # one retry: a malformed model reply should not end the journey
        except Exception as e:
            # the text agent failed twice: let the vision model pick from the screenshot instead of giving up
            r = vision.rescue(tab, snap, persona.intent, persona.history)
            if not r or PAY_RE.match(snap["by_id"][r["id"]]["name"] or ""):
                rec["actions"] = [f"persona error: {type(e).__name__}"]
                trace.append(rec)
                reached = "error"
                break
            acts, j = [{"do": "click", "id": r["id"]}], {"status": "continue", "reason": f"vision: {r['reason']}"}
        rec["reason"], rec["forced"] = j.get("reason", ""), j.get("forced", "")
        stop = None
        for a in acts:
            el = snap["by_id"][a["id"]]
            if a["do"] == "click" and PAY_RE.match(el["name"] or ""):
                stop = f"STOP at payment gate ('{el['name']}'); never pressed"
            elif a["do"] == "click" and readonly and COMMIT_RE.search(el["name"] or ""):
                stop = f"STOP at read-only boundary ('{el['name']}')"
        if stop:
            rec["actions"] = [stop]
            trace.append(rec)
            reached = "gate" if "payment" in stop else "readonly_boundary"
            break
        # a popup click goes first and alone: closing a popup can reload the page and undo other actions
        pop = [a for a in acts if a["do"] == "click" and snap["by_id"][a["id"]]["region"].startswith("popup#")]
        if pop:
            if len(acts) > 1:
                persona.history.append("NOTE: a popup had to be closed first, so your other actions on this screen were "
                                       "NOT done. Do them again now.")
            acts = pop[:1]
            if j.get("status") == "done":
                j = {**j, "status": "continue"}
        rec["fields"] = {e["name"] or e["field"]: e["value"] for e in snap["elements"] if e["kind"] in ("text", "number", "select") and e["value"]}
        if j.get("status") == "done" and not read._grounded(j.get("evidence", ""), snap["text"]) and acts:
            j = {**j, "status": "continue"}       # a claim of being done must quote the page
        if j.get("status") == "done" and done_kinds and kind not in done_kinds:
            persona.history.append(f"NOT DONE: this is a {kind} page; your goal is not reached yet. Keep going.")
            j = {**j, "status": "continue" if acts else "blocked"}
        if j.get("status") == "done":
            ev = j.get("evidence", "")
            rec["actions"] = [f"done: {ev}"]
            rec["done_evidence"] = ev if read._grounded(ev, snap["text"]) else ""
            trace.append(rec)
            reached = "done"
            break
        repeat = stalled and any(a["do"] == "click" and snap["by_id"][a["id"]]["name"] == stalled for a in acts)
        if (j.get("status") == "blocked" or not acts or repeat) and rescued < 4:
            # stuck: first try Escape for an open popup, then let the vision model pick from the screenshot
            if snap["overlays"] and stalled:
                tab.page.keyboard.press("Escape")
                tab.settle(200)
            r = vision.rescue(tab, snap, persona.intent, persona.history)
            if r and not PAY_RE.match(snap["by_id"][r["id"]]["name"] or "") and not (
                    readonly and COMMIT_RE.search(snap["by_id"][r["id"]]["name"] or "")):
                rescued += 1
                acts, j = [{"do": "click", "id": r["id"]}], {**j, "status": "continue", "reason": f"vision: {r['reason']}"}
                rec["reason"] = j["reason"]
                persona.history.append(f"{snap['url']}: click {snap['by_id'][r['id']]['name']!r} (chosen from the screenshot)")
                persona.clicks = {}
        stalled = None
        if j.get("status") == "blocked" or not acts:
            rec["actions"] = [f"blocked: {j.get('reason', '')}"]
            trace.append(rec)
            reached = "blocked"
            break
        for a in acts:
            el = snap["by_id"][a["id"]]
            try:
                tab.autofilled = []
                rec["actions"].append(tab.act(a, snap))
                if tab.autofilled:
                    rec["autofilled"] = tab.autofilled
            except Exception as e:
                rec["actions"].append(f"failed {a['do']} {el['name']!r} ({type(e).__name__})")
                continue
            positive = a["do"] in ("check", "select") or (a["do"] == "click" and a["id"] in ann["offers"])
            if positive:
                rec["chose"].append(el["name"] or el.get("question") or "")
            if a["do"] == "click":
                if a["id"] in [c["id"] for c in ann["product_cards"]] or (kind in ("home", "listing") and el["context"]):
                    ledger["listing_card"] = {"name": el["name"], "context": el["context"], "price": read.money(el["context"])}
                if el["region"].startswith("popup#"):
                    k = int(el["region"].split("#")[1])
                    if k < len(snap["overlays"]):
                        dismissed.setdefault(sig(snap["overlays"][k]["text"]), step)
        chose += rec["chose"]
        after_url = tab.page.url
        clicked_el = next((snap["by_id"][a["id"]] for a in acts if a["do"] == "click"), None)
        if clicked_el and not pop:
            try:
                same = after_url == snap["url"] and read.norm(tab.page.evaluate("() => document.body.innerText"))[:7000] == read.norm(snap["text"])
            except Exception:
                same = False
            if same:
                persona.history.append(f"NO EFFECT: clicking '{clicked_el['name']}' changed nothing on the page. Try a different control.")
                stalled = clicked_el["name"]
        try:
            after_text = tab.page.evaluate("() => document.body.innerText")
        except Exception:
            after_text = ""
        if after_url.split("#")[0] == snap["url"].split("#")[0]:
            new = [l.strip() for l in re.split(r"\n+", after_text) if l.strip() and read.norm(l) not in read.norm(snap["text"])]
            errs = [l for l in new if ERROR_RE.search(l)][:3]
            clicked = next((a["id"] for a in acts if a["do"] == "click"), None)
            if clicked and not pop:   # the browser's own form validation never shows up in the page text
                try:
                    errs += tab.page.evaluate(NATIVE_INVALID_JS, clicked)[:3]
                except Exception:
                    pass
            if errs:
                rec["refused"] = errs
                persona.history.append(f"SITE REFUSED on {snap['url']}: {'; '.join(errs)}")
                persona.refused = True
                persona.clicks = {}     # a new refusal is feedback, not a loop
        rec["events"] = tab.events[n_events:]
        n_events = len(tab.events)
        rec["popup_only"] = bool(pop)
        if pop:
            k = int(snap["by_id"][pop[0]["id"]]["region"].split("#")[1])
            rec["popup_sig"] = sig(snap["overlays"][k]["text"]) if k < len(snap["overlays"]) else ""
        if not pop:
            budget -= 1
        trace.append(rec)
    # popups that came back after being dismissed
    returns = {}
    for s, at in dismissed.items():
        later = [r["url"] for r in trace if r["step"] > at and s in r["overlays"]]
        if later:
            returns[s] = later
    out = {"persona": persona.name, "intent": persona.intent, "start": start_url, "trace": trace, "reached": reached,
           "ledger": ledger, "chose": chose, "events": list(tab.events), "popup_returns": returns,
           "actions": sum(len([a for a in r["actions"] if not a.startswith(("STOP", "done", "blocked", "failed", "persona"))])
                          for r in trace if not r.get("popup_only"))}
    if own and not keep_open:
        tab.close()
    else:
        out["tab"] = tab
    return out


def final_prices(j: dict) -> list:
    for r in reversed(j["trace"]):
        if any(p["kind"] in ("total", "subtotal", "item") for p in r["prices"]):
            return r["prices"]
    return []
