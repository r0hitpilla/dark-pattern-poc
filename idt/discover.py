"""Explore a site from its URL and plan what to test. The journey types are fixed and generic (buy something,
subscribe and cancel); the model only decides which product, which plan and where they are on this site.
"""
from harness import llm
from . import read
from .perceive import Tab

PICK_SCHEMA = {"type": "object", "required": ["visit"], "properties": {"visit": {"type": "array", "items": {"type": "string"}}}}
PLAN_SCHEMA = {"type": "object", "required": ["product", "subscription"], "properties": {
    "product": {"type": "object", "required": ["name", "found_on"], "properties": {
        "name": {"type": "string"}, "found_on": {"type": "string"}}},
    "subscription": {"type": "object", "required": ["exists"], "properties": {
        "exists": {"type": "boolean"}, "name": {"type": "string"}, "found_on": {"type": "string"}}}}}

PURCHASE = ("Buy exactly one unit of '{product}'. Nothing else: no add-ons, protection plans, memberships, trials or "
            "upgrades, and decline optional consents and newsletters. Go as far as the payment step and stop there.")
JOIN = ("Sign up for '{plan}' (use the free trial if one is offered) and then check on your account page that it is active. "
        "Do not buy any products.")
CANCEL = ("You are signed in and already have an active '{plan}'; do not sign up again. Cancel it (memberships are usually "
          "managed from the account page). Decline retention offers, discounts and pauses; keep going until the site confirms "
          "it is cancelled.")


def discover(browser, url: str, readonly=False, max_pages=6) -> dict:
    tab = Tab(browser, url, readonly)
    pages = []
    try:
        tab.goto(url)
        home = tab.snap()
        pages.append((home, read.annotate(home)))
        links = {}
        for e in home["elements"]:
            if e["kind"] == "link" and e["href"].startswith("http") and not e["offsite"] and e["href"].split("#")[0] != url.split("#")[0]:
                links.setdefault(e["href"].split("#")[0], e["name"] or e["context"][:60])
        listing = "\n".join(f"{h} — {n!r}" for h, n in list(links.items())[:90])
        try:
            pick = llm.ask_json(
                "You are mapping an online shop to audit it. From these links on its home page, choose up to "
                f"{max_pages} pages to visit that best show: a product listing or search results, a product page, the cart, "
                "any membership/subscription/pricing/trial page, and the account page. Return the URLs exactly.\n\n" + listing,
                task="discovery", schema=PICK_SCHEMA)["visit"]
        except Exception:
            pick = []
        for h in [p for p in pick if p in links][:max_pages]:
            try:
                tab.goto(h)
                s = tab.snap()
                pages.append((s, read.annotate(s)))
            except Exception:
                continue
        summary = "\n\n".join(
            f"PAGE {s['url']} (kind: {a['page_kind']})\n{s['text'][:700]}" for s, a in pages)
        # the product must be something the shopper can click: a product card if the site has any, else a content link
        cards = list(dict.fromkeys(s["by_id"][c["id"]]["name"] for s, a in pages for c in a["product_cards"]
                                   if not c["labelled_as_ad"] and s["by_id"][c["id"]]["name"]))
        options = cards or list(dict.fromkeys(e["name"] for s, _ in pages for e in s["elements"]
                                              if e["kind"] == "link" and e["region"] == "main" and e["name"]))[:60]
        schema = {**PLAN_SCHEMA, "properties": {**PLAN_SCHEMA["properties"], "product": {
            **PLAN_SCHEMA["properties"]["product"], "properties": {"name": {"type": "string", "enum": options or [""]},
                                                                 "found_on": {"type": "string"}}}}}
        try:
            plan = llm.ask_json(
                "From these pages of an online shop, choose (1) the product the shop promotes most (a deal, badge, countdown, "
                "discount or top placement; otherwise any ordinary product), with the page URL where it is listed (prefer a "
                "listing or home page that links to it), and (2) whether the site offers a membership, subscription or paid "
                "plan with a free trial, its name and the page where it is offered. Use names exactly as written.\n"
                f"PRODUCT OPTIONS (choose one exactly): {options}\n\n" + summary,
                task="discovery", schema=schema)
            if plan["product"].get("name") not in options:
                plan["product"]["name"] = options[0] if options else ""
        except Exception:
            plan = {"product": {"name": options[0] if options else "", "found_on": url}, "subscription": {"exists": False}}
    finally:
        tab.close()

    seen = {s["url"] for s, _ in pages}
    prod = plan.get("product") or {}
    sub = plan.get("subscription") or {}
    journeys = []
    if prod.get("name"):
        journeys.append({"type": "purchase", "intent": PURCHASE.format(product=prod["name"]),
                         "start": prod.get("found_on") if prod.get("found_on") in seen else url, "product": prod["name"]})
    if sub.get("exists") and sub.get("name") and not readonly:
        journeys.append({"type": "subscription", "plan": sub["name"], "start": url,
                         "join": JOIN.format(plan=sub["name"]), "cancel": CANCEL.format(plan=sub["name"]),
                         "offer_page": sub.get("found_on") if sub.get("found_on") in seen else None})
    return {"url": url, "pages": [{"url": s["url"], "kind": a["page_kind"], "snap": s, "ann": a} for s, a in pages],
            "journeys": journeys, "plan": plan}
