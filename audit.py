"""Audit any website for CCPA dark patterns, with no site configuration.

    python audit.py https://example-shop.test/            # full audit (staging/UAT with test accounts)
    python audit.py --readonly https://public-site.example/  # never creates accounts or submits personal data

Journeys always stop before payment. Run full audits only against sites you are authorised to test.
"""
import argparse
import json
import os
import pickle

from playwright.sync_api import sync_playwright

from harness import llm
from idt.audit import audit
from bench import strip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--readonly", action="store_true")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f"Local LLM: {llm.backend_name()}")
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for u in a.urls:
            print(f"\n{u}")
            r = audit(browser, u, readonly=a.readonly)
            r.update(name=u, shop=u, mode="real" if a.readonly else "audit")
            for f in r["findings"]:
                print(f"  {f['strength']:<9} {f['ccpa']:<34} {f['title']}")
            results.append(r)
        browser.close()
    stats = llm.stats()
    with open(os.path.join(a.out, "audit_findings.json"), "w") as f:
        json.dump(strip({"stats": stats, "results": results}), f, indent=1, default=str)
    from idt import report
    report.write(os.path.join(a.out, "audit_report.html"), results, stats)
    print(f"\nReport: {os.path.join(a.out, 'audit_report.html')}")


if __name__ == "__main__":
    main()
