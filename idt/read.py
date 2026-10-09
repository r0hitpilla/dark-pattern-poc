"""LLM readers: turn a page snapshot into structured facts. The model proposes; every fact that a verdict can
rest on is grounded: an amount must appear verbatim in the page text and is parsed by our code, a quote must
be copied from the page, an element id must exist in the snapshot. Anything that fails grounding is dropped.
"""
import hashlib
import json
import re

from harness import llm
from .perceive import render

_cache = {}

MONEY_RE = re.compile(r"(?P<cur>₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)\s?(?P<a>\d[\d.,]*)|(?P<b>\d[\d.,]*)\s?(?P<cur2>€|EUR|USD|INR)", re.I)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def money(s: str):
    """(amount, currency) from text like '₹1,299', '$12.99', '1.234,50 €'. Deterministic; None if no amount."""
    m = MONEY_RE.search(s or "")
    if not m:
        return None
    raw = m.group("a") or m.group("b")
    cur = (m.group("cur") or m.group("cur2") or "").upper().replace("RS.", "INR").replace("RS", "INR")
    cur = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}.get(cur, cur)
    raw = raw.rstrip(".,")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "") if raw.rfind(".") > raw.rfind(",") else raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".") if re.search(r",\d{2}$", raw) else raw.replace(",", "")
    try:
        return round(float(raw), 2), cur
    except ValueError:
        return None


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _grounded(quote: str, text: str) -> bool:
    return bool(quote) and norm(quote) in norm(text)


# ------------------------------------------------------------------ page annotation
KINDS = ["home", "listing", "product", "cart", "checkout", "payment", "order_review", "account", "subscription_offer",
         "cancellation", "confirmation", "login_or_signup", "other"]
ANNOT_SCHEMA = {"type": "object", "required": ["page_kind", "popups", "offers", "declines", "optional_choices", "forward",
                                                "product_cards", "unrelated_requirements", "fake_system_alert"], "properties": {
    "page_kind": {"type": "string", "enum": KINDS},
    "popups": {"type": "array", "items": {"type": "object", "required": ["popup", "kind"], "properties": {
        "popup": {"type": "integer"},
        "kind": {"type": "string", "enum": ["cookie_consent", "newsletter", "app_install", "offer", "system_warning", "chat", "other"]},
        "accept_id": {"type": "string"}, "reject_id": {"type": "string"}, "dismiss_id": {"type": "string"},
        "settings_id": {"type": "string"}}}},
    "offers": {"type": "array", "items": {"type": "string"}},
    "declines": {"type": "array", "items": {"type": "string"}},
    "optional_choices": {"type": "array", "items": {"type": "object", "required": ["id", "kind"], "properties": {
        "id": {"type": "string"},
        "kind": {"type": "string", "enum": ["paid_addon", "marketing_consent", "data_sharing", "auto_renew", "newsletter", "other"]}}}},
    "forward": {"type": "array", "items": {"type": "string"}},
    "product_cards": {"type": "array", "items": {"type": "object", "required": ["id", "labelled_as_ad"], "properties": {
        "id": {"type": "string"}, "labelled_as_ad": {"type": "boolean"}}}},
    "unrelated_requirements": {"type": "array", "items": {"type": "object", "required": ["what", "quote"], "properties": {
        "what": {"type": "string"}, "quote": {"type": "string"}}}},
    "cancel_offline_only": {"type": "boolean"},
    "fake_system_alert": {"type": "boolean"}}}


def annotate(snap: dict) -> dict:
    """What kind of page this is and what role each relevant control plays."""
    k = _key("annot", snap["url"].split("?")[0], snap["text"][:3000], [(e["id"], e["name"]) for e in snap["elements"][:140]])
    if k in _cache:
        return _cache[k]
    pops = "\n".join(f"popup#{o['idx']} (covers {int(o['cover'] * 100)}% of screen): {o['text'][:300]!r}" for o in snap["overlays"]) or "(none)"
    prompt = (
        "You analyse one screen of a website for an audit of consumer-protection issues. Classify the screen and the "
        "role of its controls. Use only element ids from the CONTROLS list.\n"
        "- popups: for each popup/banner listed, its kind and the ids that accept, reject (or 'necessary only'), "
        "dismiss/close it, or open its settings, where present.\n"
        "- offers: controls that ACCEPT an optional paid extra, upgrade, membership, trial or add-on.\n"
        "- declines: controls that DECLINE such an offer (e.g. 'No thanks', 'Continue without').\n"
        "- optional_choices: checkboxes/radios/switches a shopper does not need for the purchase (paid add-ons, marketing "
        "or partner consent, newsletter, auto-renew, data sharing).\n"
        "- forward: controls that move a user forward in buying, checking out, subscribing or cancelling "
        "(add to cart, checkout, continue, next, view cart, product links on a listing...).\n"
        "- product_cards: links to individual products/results in a listing or search results, and whether each card "
        "is visibly labelled as an advertisement (Ad, Sponsored, Promoted, Partner).\n"
        "- unrelated_requirements: things this screen REQUIRES that a shopper would not need to complete their task "
        "(creating an account with no guest option, joining a mailing list, installing an app, sharing contacts), with a "
        "verbatim quote.\n"
        "- cancel_offline_only: true if this screen says cancelling can only be done by phone, email, chat or post.\n"
        "- fake_system_alert: true if the screen imitates a browser/operating-system/security warning or tells the user "
        "to download or install software.\n\n"
        f"URL: {snap['url']}\nTITLE: {snap['title']}\nPOPUPS:\n{pops}\n\nPAGE TEXT:\n{snap['text'][:3000]}\n\n"
        f"CONTROLS:\n{render(snap)}")
    try:
        j = llm.ask_json(prompt, task="page annotation", schema=ANNOT_SCHEMA)
    except Exception:
        j = {}
    ids = snap["by_id"]
    nov = len(snap["overlays"])
    out = {
        "page_kind": j.get("page_kind") if j.get("page_kind") in KINDS else "other",
        "popups": [{**p, "kind": p.get("kind") or "other"} for p in j.get("popups", [])
                   if isinstance(p, dict) and isinstance(p.get("popup"), int) and p["popup"] < nov],
        "offers": [i for i in j.get("offers", []) if i in ids],
        "declines": [i for i in j.get("declines", []) if i in ids],
        "optional_choices": [{"id": c["id"], "kind": c.get("kind") or "other"} for c in j.get("optional_choices", [])
                             if isinstance(c, dict) and c.get("id") in ids and ids[c["id"]]["kind"] in ("checkbox", "radio", "select")],
        "forward": [i for i in j.get("forward", []) if i in ids],
        "product_cards": [{"id": c["id"], "labelled_as_ad": bool(c.get("labelled_as_ad"))} for c in j.get("product_cards", [])
                          if isinstance(c, dict) and c.get("id") in ids],
        "unrelated_requirements": [{"what": r.get("what") or "an unrelated step", "quote": r["quote"]} for r in j.get("unrelated_requirements", [])
                                   if isinstance(r, dict) and _grounded(r.get("quote"), snap["text"])],
        "cancel_offline_only": bool(j.get("cancel_offline_only")),
        "fake_system_alert": bool(j.get("fake_system_alert")),
    }
    for p in out["popups"]:
        for f in ("accept_id", "reject_id", "dismiss_id", "settings_id"):
            if p.get(f) not in ids:
                p[f] = None
    _cache[k] = out
    return out


# ------------------------------------------------------------------ prices
PRICE_SCHEMA = {"type": "object", "required": ["lines"], "properties": {"lines": {"type": "array", "items": {
    "type": "object", "required": ["label", "amount_text", "kind"], "properties": {
        "label": {"type": "string"}, "amount_text": {"type": "string"},
        "kind": {"type": "string", "enum": ["item", "addon", "fee", "shipping", "tax", "discount", "subtotal", "total",
                                            "recurring", "other"]},
        "in_order": {"type": "boolean"}, "quantity": {"type": "integer"}, "period": {"type": "string"}}}}}}


def prices(snap: dict) -> list:
    """Every price on the screen with its role. amount_text must appear on the page; the number is parsed by us."""
    k = _key("prices", snap["text"][:5000])
    if k in _cache:
        return _cache[k]
    try:
        j = llm.ask_json(
            "List every price shown on this shopping-site screen, as it applies to the shopper's order or the product "
            "on screen. kind: item (the product itself), addon (optional extra, warranty, protection, gift wrap), fee "
            "(service, convenience, handling, platform fees), shipping/delivery, tax, discount, subtotal, total (the "
            "amount payable), recurring (a membership/subscription charge; give its period). quantity: units of an item "
            "line if shown. in_order: true only if the line is part of the shopper's current order/basket/total; false "
            "for something merely offered (e.g. a button 'Add protection for 9.99'). amount_text must be copied exactly "
            "from the page, including the currency symbol. Ignore prices of other products in recommendations.\n\nPAGE TEXT:\n" + snap["text"][:5000],
            task="price reading", schema=PRICE_SCHEMA)
    except Exception:
        j = {}
    out = []
    for ln in j.get("lines", []):
        amt = money(ln.get("amount_text", ""))
        if amt and _grounded(ln["amount_text"], snap["text"]):
            out.append({"label": ln.get("label", "")[:80], "amount": amt[0], "currency": amt[1], "kind": ln["kind"],
                        "quantity": ln.get("quantity"), "period": ln.get("period"), "quote": ln["amount_text"],
                        "in_order": ln.get("in_order", True) is not False})
    _cache[k] = out
    return out


# ------------------------------------------------------------------ claims
CLAIM_SCHEMA = {"type": "object", "required": ["claims"], "properties": {"claims": {"type": "array", "items": {
    "type": "object", "required": ["kind", "quote"], "properties": {
        "kind": {"type": "string", "enum": ["countdown", "deadline_date", "stock_count", "viewers", "recent_purchases",
                                            "recurring_terms", "other"]},
        "quote": {"type": "string"}, "displayed_time": {"type": "string"}, "units": {"type": "integer"}}}}}}


def claims(text: str) -> list:
    """Checkable urgency, scarcity, social-proof and recurring-billing claims, each with a verbatim quote."""
    k = _key("claims", text[:4000])
    if k in _cache:
        return _cache[k]
    try:
        j = llm.ask_json(
            "Extract every factual claim on this page that a shopper could check: countdown (running timer; put the exact "
            "timer text such as '14:58' in displayed_time), deadline_date, stock_count (units claimed left; number in "
            "units), viewers ('12 people viewing'), recent_purchases, recurring_terms (any statement of a repeating "
            "charge, renewal or what happens after a free trial). quote must be copied verbatim from the page.\n\n"
            "PAGE TEXT:\n" + text[:4000], task="claim extraction", schema=CLAIM_SCHEMA)
    except Exception:
        j = {}
    out = []
    for c in j.get("claims", []):
        if not _grounded(c.get("quote"), text):
            continue
        if c["kind"] == "countdown":
            t = (c.get("displayed_time") or "").strip()
            if not (re.fullmatch(r"(\d+:)?\d{1,2}:\d{2}", t) and t in text):
                continue
        if c["kind"] == "stock_count" and not (isinstance(c.get("units"), int) and c["units"] > 0 and str(c["units"]) in c["quote"]):
            continue
        out.append(c)
    _cache[k] = out
    return out


# ------------------------------------------------------------------ state questions
STATE_SCHEMA = {"type": "object", "required": ["answer", "quote"], "properties": {
    "answer": {"type": "string", "enum": ["yes", "no", "unclear"]}, "quote": {"type": "string"}}}


def ask_state(snap: dict, question: str) -> dict:
    """A yes/no question about the page (e.g. 'is a paid subscription active?'), answered with a grounding quote.
    An answer whose quote is not on the page is returned as 'unclear'."""
    k = _key("state", question, snap["text"][:4000])
    if k in _cache:
        return _cache[k]
    try:
        j = llm.ask_json(f"QUESTION: {question}\nAnswer yes, no or unclear from this page only, and quote the exact page "
                         f"text that shows it.\n\nPAGE TEXT:\n{snap['text'][:4000]}", task="state reading", schema=STATE_SCHEMA)
    except Exception:
        j = {"answer": "unclear", "quote": ""}
    if j.get("answer") != "unclear" and not _grounded(j.get("quote"), snap["text"]):
        j = {"answer": "unclear", "quote": ""}
    _cache[k] = j
    return j
