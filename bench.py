"""Benchmark the generic engine: the same code, with zero site configuration, against three structurally different
test shops (each in a dark and an honest version) and, optionally, real test-automation websites.

    python bench.py                   # 3 shops × {dark, honest}, scored against seeded ground truth
    python bench.py --real            # also audit real public test shops (read-only, unscored)
    python bench.py --shops brewbox   # one shop

Ground truth is fetched only after a shop has been audited; the engine never sees it.
"""
import argparse
import json
import logging
import os
import pickle
import threading
import time

import requests
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from harness import llm
from idt.audit import audit
from idt.oracles import CCPA
from shop.app import create_app as kartiq
from shops.brewbox import create_app as brewbox
from shops.voltaro import create_app as voltaro

SHOPS = {"kartiq": ("Kartiq", kartiq), "brewbox": ("Brewbox", brewbox), "voltaro": ("Voltaro", voltaro)}
REAL = ["https://automationexercise.com/", "https://www.demoblaze.com/", "https://practicesoftwaretesting.com/",
        "https://sauce-demo.myshopify.com/"]


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in ("shot", "shots", "snap", "tab")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shops", default="kartiq,brewbox,voltaro")
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--only-real", action="store_true")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    os.makedirs(a.out, exist_ok=True)
    print(f"Local LLM: {llm.backend_name()}")
    results, t0 = [], time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        port = 5400
        for key in ([] if a.only_real else a.shops.split(",")):
            name, factory = SHOPS[key]
            for mode in ("dark", "clean"):
                port += 1
                srv = make_server("127.0.0.1", port, factory(mode), threaded=True)
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                label = f"{name} ({'dark' if mode == 'dark' else 'honest'})"
                print(f"\n{label}")
                t = time.time()
                try:
                    res = audit(browser, f"http://127.0.0.1:{port}/")
                except Exception as e:
                    res = {"error": repr(e), "findings": [], "passes": []}
                truth = set(requests.get(f"http://127.0.0.1:{port}/__ground_truth").json()["seeded"])
                found = {f["key"] for f in res["findings"]}
                res.update(name=label, shop=name, mode=mode, truth=sorted(truth), found=sorted(found),
                           tp=sorted(found & truth), fn=sorted(truth - found), fp=sorted(found - truth),
                           seconds=round(time.time() - t))
                print(f"  found {len(found & truth)}/{len(truth)} seeded · false alarms: {sorted(found - truth) or 'none'}"
                      f" · missed: {sorted(truth - found) or 'none'} · {res['seconds']}s")
                for f in res["findings"]:
                    if f["key"] not in truth:
                        print(f"    false alarm detail: {f['title']} | {f['observed'][:200]}")
                results.append(res)
                srv.shutdown()
        if a.real or a.only_real:
            for url in REAL:
                print(f"\n{url} (real site, read-only)")
                t = time.time()
                try:
                    res = audit(browser, url, readonly=True)
                except Exception as e:
                    res = {"error": repr(e), "findings": [], "passes": []}
                res.update(name=url, shop=url, mode="real", seconds=round(time.time() - t))
                print(f"  findings: {[f['key'] for f in res['findings']] or 'none'} · {res['seconds']}s")
                results.append(res)
        browser.close()

    scored = [r for r in results if r["mode"] != "real"]
    tp, fn, fp = (sum(len(r[k]) for r in scored) for k in ("tp", "fn", "fp"))
    stats = llm.stats()
    print(f"\nTotal: {tp}/{tp + fn} seeded patterns found, {fp} false alarms, across {len(scored)} shop variants "
          f"in {round(time.time() - t0)}s · {stats['calls']} LLM calls ({stats['cached']} cached, {stats['failures']} failed)")
    with open(os.path.join(a.out, "idt_results.pkl"), "wb") as f:
        pickle.dump({"results": results, "stats": stats}, f)
    with open(os.path.join(a.out, "idt_findings.json"), "w") as f:
        json.dump(strip({"stats": stats, "results": results}), f, indent=1, default=str)
    try:
        from idt import report
        report.write(os.path.join(a.out, "idt_report.html"), results, stats)
        print(f"Report: {os.path.join(a.out, 'idt_report.html')}")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
