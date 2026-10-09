"""End-to-end demo: start the dark and honest Kartiq shops, run Intent-Divergence Testing and the
single-screen baseline against both, score against the seeded ground truth, write the report.

    python run_demo.py                 # uses a local Ollama model if one is installed
    DP_NO_LLM=1 python run_demo.py     # deterministic heuristics only
    DP_NO_VLM=1 python run_demo.py     # skip the (slow) screenshot-VLM baseline
"""
import argparse
import json
import os
import threading

import requests
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from shop.app import create_app, SEEDED_PATTERNS
from harness import llm, report, vlm_baseline
from harness.baseline import recognise
from harness.checks import falsity, friction, nagging
from harness.journey import run_purchase
from harness.oracles import evaluate, CCPA
from harness.personas import Agent, Careful, Hurried, Intent

INTENT_TEXT = "buy one Classic Black Tee — no add-ons, no subscription, decline optional consents"
AVOID = ("plus", "trial", "protect", "insurance", "subscribe", "membership")
PURCHASE = Intent(goal_words={"add to cart": 3, "checkout": 3, "proceed": 2, "continue": 2, "review": 2, "next": 1},
                  avoid_words=AVOID, decline_optional=True, description=INTENT_TEXT)


def target(name, base):
    return {"name": name, "base": base, "product_path": "/product/tee", "product_name": "Classic Black Tee",
            "account_path": "/account", "inventory_api": "/api/inventory/tee", "member_key": "Membership",
            "member_none": "Not a member", "consent_key": "Partner offers & data sharing",
            "intent": INTENT_TEXT, "avoid_words": AVOID,
            "nag_paths": ["/", "/product/tee", "/product/cap", "/plus", "/account", "/"]}


def serve(app, port):
    srv = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def audit(browser, cfg):
    personas = (Careful, Hurried) + ((Agent,) if llm.available() else ())
    print(f"  · {cfg['name']}: persona journeys ({', '.join(p.name for p in personas)})")
    journeys = [run_purchase(browser, cfg["base"], cfg["product_path"], cfg["account_path"], p(), PURCHASE)
                for p in personas]
    print(f"  · {cfg['name']}: falsity, friction, nagging")
    fals = falsity(browser, cfg["base"], cfg["product_path"], cfg["inventory_api"])
    fric = friction(browser, cfg["base"], cfg["account_path"], cfg["member_key"], cfg["member_none"])
    nag = nagging(browser, cfg["base"], cfg["nag_paths"])
    findings, passes, delta = evaluate(cfg, journeys, fals, fric, nag)
    screens = [s for j in journeys for s in j["trace"]]
    vlm = None
    if llm.vision_model():
        print(f"  · {cfg['name']}: screenshot-VLM baseline ({llm.vision_model()})")
        vlm = vlm_baseline.recognise(screens)
    return {"name": cfg["name"], "journeys": journeys, "fals": fals, "fric": fric, "nag": nag,
            "findings": findings, "passes": passes, "delta": delta, "base": recognise(screens), "vlm": vlm,
            "agent": agent_check(journeys)}


def agent_check(journeys):
    """Did the LLM navigator, given only the sentence of intent, reach the same end state as the scripted
    careful persona? Agreement means navigation needed no site-specific goal words."""
    by = {j["persona"]: j for j in journeys}
    if "agent" not in by:
        return None
    c, a = by["careful"], by["agent"]
    keys = [("payable", c["payable"], a["payable"])] + [(k, c["account"].get(k), a["account"].get(k)) for k in c["account"]]
    return {"agrees": all(x == y for _, x, y in keys), "diff": [k for k, x, y in keys if x != y],
            "reached_gate": a["reached_gate"], "steps": len(a["trace"])}


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ("shot", "shots", "candidates", "checkboxes", "text")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dark_srv, clean_srv = serve(create_app("dark"), 5101), serve(create_app("clean"), 5102)
    print(f"Local LLM: {llm.backend_name()} · VLM baseline: {llm.vision_model() or 'off'}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        dark = audit(browser, target("Kartiq (dark)", "http://127.0.0.1:5101"))
        clean = audit(browser, target("Kartiq (honest)", "http://127.0.0.1:5102"))
        browser.close()

    # scoring happens only after testing; the harness never sees the ground truth
    truth = set(requests.get("http://127.0.0.1:5101/__ground_truth").json()["seeded"])
    hd, hc = {f["key"] for f in dark["findings"]}, {f["key"] for f in clean["findings"]}
    score = [{"key": k, "desc": SEEDED_PATTERNS[k], "ccpa": CCPA[k], "h_dark": k in hd, "h_clean": k in hc,
              "b_dark": k in dark["base"], "b_clean": k in clean["base"],
              "v_dark": k in (dark["vlm"] or {}), "v_clean": k in (clean["vlm"] or {})} for k in SEEDED_PATTERNS]
    has_vlm = dark["vlm"] is not None and clean["vlm"] is not None
    assert truth == set(SEEDED_PATTERNS)

    stats = llm.stats()
    report.write(os.path.join(a.out, "report.html"), dark, clean, score, llm.backend_name(), INTENT_TEXT,
                 has_vlm, stats)
    with open(os.path.join(a.out, "findings.json"), "w") as f:
        json.dump(strip({"llm_backend": llm.backend_name(), "llm_stats": stats, "intent": INTENT_TEXT,
                         "score": score, "dark": dark, "clean": clean}), f, indent=2, default=str)

    head = "\nPattern                  Harness(dark) Harness(clean) Lexical(dark) Lexical(clean)"
    print(head + (" VLM(dark) VLM(clean)" if has_vlm else ""))
    for r in score:
        print(f"{r['key']:<24} {'✓' if r['h_dark'] else '✗':^13} {'FP' if r['h_clean'] else '·':^14} "
              f"{'✓' if r['b_dark'] else '✗':^13} {'FP' if r['b_clean'] else '·':^14}"
              + (f" {'✓' if r['v_dark'] else '✗':^9} {'FP' if r['v_clean'] else '·':^10}" if has_vlm else ""))
    print(f"\nHarness: {sum(r['h_dark'] for r in score)}/{len(score)} detected, {len(hc)} false alarms")
    print(f"Lexical baseline: {sum(r['b_dark'] for r in score)}/{len(score)} detected, {len(clean['base'])} false alarms")
    if has_vlm:
        print(f"VLM baseline ({stats['vision_model']}): {sum(r['v_dark'] for r in score)}/{len(score)} detected, "
              f"{len(clean['vlm'])} false alarms")
    for shop in (dark, clean):
        if shop["agent"]:
            ag = shop["agent"]
            print(f"LLM navigator on {shop['name']}: "
                  + ("same end state as scripted careful persona" if ag["agrees"] else f"differs on {', '.join(ag['diff'])}")
                  + (f"; join/cancel {shop['fric']['agent']['join']['actions']}/{shop['fric']['agent']['cancel']['actions']} actions"
                     if shop["fric"].get("agent") else ""))
    print(f"LLM calls: {stats['calls']} ({stats['cached']} cached, {stats['failures']} failed), {stats['seconds']}s model time")
    print(f"Report: {os.path.join(a.out, 'report.html')}")
    dark_srv.shutdown(); clean_srv.shutdown()


if __name__ == "__main__":
    main()
