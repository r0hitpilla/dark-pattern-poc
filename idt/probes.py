"""Active probes: tests that put a site's claims to the test, the way an inspector would.

temporal  : open the page in several fresh sessions over time. A real deadline is the same moment for everyone.
quantity  : the page says "only N left": try to put N+2 in the basket. A shop that accepts them had more than N.
consent   : count what it takes to accept vs to refuse the cookie/consent banner, and whether refusal sticks.
ads       : listing cards that lead to an advertiser or ad-click URL but are not labelled as ads.
"""
import json
import re
import time
from datetime import datetime

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


def clock(browser, url: str) -> dict | None:
    """Jump the browser's own clock 3 hours ahead and reload. A real deadline stays where it was (or expires);
    a countdown computed from 'now' starts again. Catches client-side evergreen timers without any back end."""
    tab = Tab(browser, url)
    try:
        t0 = time.time()
        tab.page.clock.install(time=datetime.fromtimestamp(t0))
        tab.goto(url)
        c1 = next((c for c in read.claims(tab.snap()["text"]) if c["kind"] == "countdown"), None)
        if not c1:
            return None
        tab.page.clock.fast_forward("03:00:00")
        tab.page.reload(wait_until="domcontentloaded")
        tab.settle()
        c2 = next((c for c in read.claims(tab.snap()["text"]) if c["kind"] == "countdown"), None)
    finally:
        tab.close()
    d1 = t0 + _secs(c1["displayed_time"])
    if not c2 or _secs(c2["displayed_time"]) == 0:
        return {"url": url, "verdict": "expired", "before": c1["displayed_time"], "after": c2 and c2["displayed_time"]}
    d2 = t0 + 3 * 3600 + _secs(c2["displayed_time"])
    return {"url": url, "verdict": "restarts" if d2 - d1 > 60 else "fixed", "before": c1["displayed_time"],
            "after": c2["displayed_time"], "moved_s": round(d2 - d1)}


STOCK_KEY = re.compile(r"(stock|inventory|available_?(qty|quantity|units)?|quantity_?available|units_?(left|available)|qty)$", re.I)


def site_data_stock(captured: list, item: str, claimed: int) -> dict | None:
    """Look in the JSON the site's own pages downloaded for a stock figure for this product. The site's data is
    the system of record we can see from outside."""
    words = {w for w in re.findall(r"[a-z0-9]+", item.lower()) if len(w) > 2}

    def walk(o, ctx):
        if isinstance(o, dict):
            names = " ".join(str(v).lower() for v in o.values() if isinstance(v, str))
            here = ctx or (words and len(words & set(re.findall(r"[a-z0-9]+", names))) >= max(1, len(words) // 2))
            for k, v in o.items():
                if here and isinstance(v, (int, float)) and not isinstance(v, bool) and STOCK_KEY.search(k):
                    yield k, v
                yield from walk(v, here)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v, ctx)
    for c in captured:
        try:
            data = json.loads(c["body"])
        except Exception:
            continue
        for k, v in walk(data, False):
            if v > claimed:
                return {"url": c["url"], "field": k, "value": v, "claimed": claimed}
    return None


def quantity(browser, product_url: str, claimed: int, item: str, readonly=False) -> dict:
    want = claimed + 2
    intent = (f"Put {want} units of '{item}' in the basket: set the quantity to {want} if there is a quantity field, "
              f"otherwise add it to the basket {want} times. Then open the basket. Decline every extra, offer and popup. "
              f"Stop when you see the basket.")
    j = run(browser, product_url, Careful(intent, readonly), readonly=readonly, max_steps=7 + want)
    qty, quote = None, ""
    words = item.lower()
    for r in reversed(j["trace"]):
        if r["page_kind"] not in ("cart", "checkout", "order_review", "payment"):
            continue
        lines = [p for p in r["prices"] if p["kind"] == "item" and p.get("in_order", True)]
        withq = [p for p in lines if p.get("quantity")]
        if withq:
            qty, quote = max(p["quantity"] for p in withq), withq[0]["label"]
            break
        same_rows = [p for p in lines if read._grounded(p["label"], item) or read._grounded(item, p["label"]) or
                     len(set(p["label"].lower().split()) & set(words.split())) >= 2]
        if same_rows:      # carts that list one row per unit
            qty, quote = len(same_rows), same_rows[0]["label"]
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
