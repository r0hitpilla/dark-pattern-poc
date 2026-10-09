"""Audit one website from its URL: discover, walk, probe, judge."""
from . import read
from .agent import Careful, Hurried
from .discover import discover
from .journey import run
from .oracles import evaluate
from . import probes


def safe(log, name, fn, *args, **kw):
    """Run one probe; a failure costs that probe, not the audit."""
    try:
        return fn(*args, **kw)
    except Exception as e:
        log(f"  · {name} failed: {type(e).__name__}")
        return None

MEMBER_Q = "Does this page show that the user currently has an active paid membership, subscription, or a free trial of one?"


def _account_state(j, account_url):
    """Ask the account page (system of record as the user sees it) whether a membership is active."""
    tab = j.get("tab")
    if not tab or not account_url:
        return None
    try:
        tab.goto(account_url)
        s = tab.snap()
        st = read.ask_state(s, MEMBER_Q)
        return {"answer": st["answer"], "quote": st["quote"], "prices": read.prices(s), "shot": tab.shot()}
    except Exception:
        return None


def audit(browser, url: str, readonly=False, log=print) -> dict:
    log(f"  · discovering {url}")
    d = discover(browser, url, readonly)
    account = next((p["url"] for p in d["pages"] if p["kind"] == "account"), None)
    a = {"url": url, "readonly": readonly, "plan": d["plan"], "journeys_planned": d["journeys"], "temporal": [],
         "pages": [{"url": p["url"], "kind": p["kind"]} for p in d["pages"]], "membership": {}}
    recs = [{"url": p["url"], "cards": [{"href": p["snap"]["by_id"][c["id"]]["href"], "offsite": p["snap"]["by_id"][c["id"]]["offsite"],
                                         "card": p["snap"]["by_id"][c["id"]]["context"] or p["snap"]["by_id"][c["id"]]["name"],
                                         "labelled": c["labelled_as_ad"]} for c in p["ann"]["product_cards"]]} for p in d["pages"]]
    tabs = []
    pj = next((j for j in d["journeys"] if j["type"] == "purchase"), None)
    if pj:
        log(f"  · purchase journey: '{pj['product']}' (careful, hurried)")
        ends = {"checkout", "payment", "order_review"} | ({"login_or_signup"} if readonly else set())
        c = run(browser, pj["start"], Careful(pj["intent"], readonly), readonly=readonly, keep_open=True, done_kinds=ends)
        h = run(browser, pj["start"], Hurried(pj["intent"], readonly), readonly=readonly, keep_open=True, done_kinds=ends)
        tabs += [c["tab"], h["tab"]]
        a["purchase"] = {"careful": c, "hurried": h}
        for who, j in (("careful", c), ("hurried", h)):
            st = _account_state(j, account)
            if st:
                a["membership"][who] = st["answer"]
        recs += c["trace"] + h["trace"]
        claimed = [(r["url"].split("#")[0], cl) for r in c["trace"] for cl in r["claims"] if cl["kind"] in ("countdown", "stock_count")]
        a["clock"] = []
        for u in dict.fromkeys(u for u, cl in claimed if cl["kind"] == "countdown"):
            log(f"  · clock probe: {u}")
            ck = safe(log, "clock probe", probes.clock, browser, u)
            if ck:
                a["clock"].append(ck)
        for u in dict.fromkeys(u for u, _ in claimed):
            log(f"  · temporal probe: {u}")
            t = safe(log, "temporal probe", probes.temporal, browser, u)
            if t:
                a["temporal"].append(t)
        stock = next(((u, cl) for u, cl in claimed if cl["kind"] == "stock_count"), None)
        if stock:
            a["site_data_stock"] = probes.site_data_stock(c["tab"].json + h["tab"].json, pj["product"], stock[1]["units"])
            log(f"  · quantity probe: claimed {stock[1]['units']} left")
            a["quantity"] = safe(log, "quantity probe", probes.quantity, browser, stock[0], stock[1]["units"], pj["product"], readonly)
    sj = next((j for j in d["journeys"] if j["type"] == "subscription"), None)
    if sj:
        log(f"  · subscription journey: join and cancel '{sj['plan']}'")
        join = run(browser, sj["start"], Careful(sj["join"]), keep_open=True)
        tabs.append(join["tab"])
        st = _account_state(join, account)
        a["recurring_after_join"] = [p for p in (st or {}).get("prices", []) if p["kind"] == "recurring"]
        cancel = run(browser, sj["start"], Careful(sj["cancel"]), tab=join["tab"], keep_open=True)
        st2 = _account_state(cancel, account)
        a["membership"]["after_join"] = (st or {}).get("answer")
        a["membership"]["after_cancel"] = (st2 or {}).get("answer")
        a["subscription"] = {"join": join, "cancel": cancel}
        recs += join["trace"] + cancel["trace"]
    log("  · consent probe")
    a["consent"] = safe(log, "consent probe", probes.consent, browser, url)
    a["ads"] = probes.ads(recs)
    for t in tabs:
        t.close()
    for j in [x for x in ((a.get("purchase") or {}).values())] + [x for x in ((a.get("subscription") or {}).values())]:
        j.pop("tab", None)
    a["findings"], a["passes"] = evaluate(a)
    return a
