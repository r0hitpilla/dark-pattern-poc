"""Active probes: tests that put a site's claims to the test, the way an inspector would.

temporal  : open the page in several fresh sessions over time. A real deadline is the same moment for everyone.
quantity  : the page says "only N left": try to put N+2 in the basket. A shop that accepts them had more than N.
consent   : count what it takes to accept vs to refuse the cookie/consent banner, and whether refusal sticks.
ads       : listing cards that lead to an advertiser or ad-click URL but are not labelled as ads.
"""
import re
import time

from . import read
from .agent import Careful
from .journey import run, sig
from .perceive import Tab


def _secs(t: str) -> int:
    s = 0
    for p in t.split(":"):
        s = s * 60 + int(p)
    return s


def temporal(browser, url: str, sessions=3, gap=4.0) -> dict:
    obs = []
    for i in range(sessions):
        tab = Tab(browser, url)
        try:
            tab.goto(url)
            tab.page.wait_for_timeout(1200)
            t = time.time()
            s = tab.snap()
            cl = read.claims(s["text"])
            o = {"session": i + 1, "at": t, "claims": cl, "shot": tab.shot() if i == 0 else None}
            cd = next((c for c in cl if c["kind"] == "countdown"), None)
            if cd:
                o["countdown"] = cd["displayed_time"]
                o["deadline"] = t + _secs(cd["displayed_time"].strip())
            st = next((c for c in cl if c["kind"] == "stock_count"), None)
            if st:
                o["stock"] = st["units"]
            obs.append(o)
        finally:
            tab.close()
        if i < sessions - 1:
            time.sleep(gap)
    out = {"url": url, "observations": obs}
    dl = [o["deadline"] for o in obs if "deadline" in o]
    if len(dl) >= 2:
        spread = max(dl) - min(dl)
        out["countdown"] = {"spread_s": round(spread, 1), "elapsed_s": round(obs[-1]["at"] - obs[0]["at"], 1),
                            "verdict": "moves" if spread > 5 else "fixed", "seen": [o.get("countdown") for o in obs]}
    stocks = [o["stock"] for o in obs if "stock" in o]
    if stocks:
        out["stock_claims"] = stocks
    return out


def quantity(browser, product_url: str, claimed: int, item: str, readonly=False) -> dict:
    want = claimed + 2
    intent = (f"On this product page, set the quantity of '{item}' to {want} and add it to the basket, then open the "
              f"basket. Decline every extra, offer and popup. Stop when you see the basket.")
    j = run(browser, product_url, Careful(intent, readonly), readonly=readonly, max_steps=7)
    qty, quote = None, ""
    for r in reversed(j["trace"]):
        if r["page_kind"] not in ("cart", "checkout", "order_review", "payment"):
            continue
        lines = [p for p in r["prices"] if p["kind"] == "item" and p.get("quantity")]
        if lines:
            qty, quote = max(p["quantity"] for p in lines), lines[0]["label"]
            break
    refused = [m for r in j["trace"] for m in r.get("refused", [])]
    # only conclusive if the field really held the requested quantity when the add-to-basket click happened
    asked = any(str(want) in r.get("fields", {}).values() and any(x.startswith("click") for x in r["actions"]) for r in j["trace"])
    verdict = ("accepted_more" if qty and qty > claimed else
               "capped" if qty and (asked or refused) else "unknown")
    return {"claimed": claimed, "tried": want, "in_basket": qty, "quote": quote, "refused": refused, "verdict": verdict,
            "trace": j["trace"]}


def consent(browser, url: str) -> dict | None:
    tab = Tab(browser, url)
    try:
        tab.goto(url)
        s = tab.snap()
        ann = read.annotate(s)
        ban = next((p for p in ann["popups"] if p["kind"] == "cookie_consent"), None)
        if not ban:
            return None
        ov = s["overlays"][ban["popup"]]
        inside = [e for e in s["elements"] if e["region"] == f"popup#{ban['popup']}" and e["kind"] in ("button", "link")]
        acc = s["by_id"].get(ban.get("accept_id"))
        rej = s["by_id"].get(ban.get("reject_id"))
        shot = tab.shot()
    finally:
        tab.close()
    out = {"banner": ov["text"][:300], "cover": ov["cover"], "accept": acc and acc["name"], "reject_first_layer": rej and rej["name"],
           "accept_actions": 1 if acc else None, "shot": shot,
           "salience_ratio": round(acc["salience"] / max(rej["salience"], 1), 1) if acc and rej else None}
    if acc and not rej:
        top = max(inside, key=lambda e: e["salience"]) if inside else None
        out["most_prominent"] = top and top["name"]
    # refuse path, walked by the careful agent in a fresh session
    banner = sig(ov["text"])
    tab = Tab(browser, url)
    try:
        j = run(browser, url, Careful("Refuse all optional cookies on this site's cookie banner, keeping only strictly "
                                      "necessary ones. You are done as soon as the banner is gone with optional cookies "
                                      "refused. Do nothing else on the site."), max_steps=6, tab=tab, keep_open=True)
        gone_at = next((i for i, r in enumerate(j["trace"]) if banner not in r["overlays"]), None)
        # count only what it took to refuse: actions on the banner (and its settings), not on unrelated popups
        mine = [r for r in j["trace"][:gone_at] if not r.get("popup_sig") or r["popup_sig"] == banner]
        out["reject_actions"] = sum(len(r["actions"]) for r in mine) if gone_at is not None else None
        out["reject_path"] = [a for r in j["trace"][:gone_at or len(j["trace"])] for a in r["actions"]]
        out["refused_ok"] = gone_at is not None
        if gone_at is not None:   # does the refusal stick on the next page?
            tab.goto(url)
            out["returns_after_refusal"] = banner in [sig(o["text"]) for o in tab.snap()["overlays"]]
    finally:
        tab.close()
    return out


AD_URL = re.compile(r"[?&](ad|adid|ad_id|aclk|gclid|clickid|click_id|sponsored|adurl|campaign_id)=|"
                    r"/(aclk|adclick|ads?|go|out|redirect|click|sponsored|track)(/|\?)", re.I)


def ads(recs: list) -> list:
    """recs: trace records (with 'cards' and 'url'). Unlabelled result cards that lead to an advertiser or ad-click URL."""
    hits, seen = [], set()
    for r in recs:
        for c in r.get("cards", []):
            if not c["href"] or c["href"] in seen:
                continue
            seen.add(c["href"])
            if c["offsite"] or AD_URL.search(c["href"]):
                hits.append({"page": r["url"], **c})
    return hits
