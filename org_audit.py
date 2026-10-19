"""Audit every site belonging to one or more organisations and roll each organisation's results up
into one compliance-facing report (executive summary + per-site evidence), reusing the idt/ engine
unchanged: every site is still audited from nothing but its URL.

Config file (JSON, see orgs.example.json):
    {"orgs": [{"name": "Acme Corp", "sites": [{"label": "Acme Shop", "url": "https://shop.acme.example/"}]}]}

    python org_audit.py --config orgs.json                   # full audits (staging/UAT with test accounts)
    python org_audit.py --config orgs.json --readonly        # never creates accounts or submits personal data
    python org_audit.py --config orgs.json --org "Acme Corp" # just one organisation from the file

Journeys always stop before payment. Run full audits only against sites you are authorised to test.
"""
import argparse
import copy
import json
import os
import re

from playwright.sync_api import sync_playwright

from harness import llm
from idt.audit import audit
from bench import strip


def load_orgs(path: str) -> list:
    with open(path) as f:
        cfg = json.load(f)
    orgs = cfg["orgs"] if isinstance(cfg, dict) else cfg
    for o in orgs:
        if not o.get("sites"):
            raise SystemExit(f"{path}: organisation {o.get('name')!r} has no sites")
    return orgs


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "org"


def _diff_stats(before: dict, after: dict) -> dict:
    """llm.stats() accumulates for the whole process; subtract a snapshot to get one org's share."""
    by_task = {k: {"calls": v["calls"] - before["by_task"].get(k, {}).get("calls", 0),
                    "cached": v["cached"] - before["by_task"].get(k, {}).get("cached", 0),
                    "seconds": round(v["seconds"] - before["by_task"].get(k, {}).get("seconds", 0), 1)}
               for k, v in after["by_task"].items()}
    return {**after, "calls": after["calls"] - before["calls"], "cached": after["cached"] - before["cached"],
            "failures": after["failures"] - before["failures"],
            "seconds": round(after["seconds"] - before["seconds"], 1), "by_task": by_task}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="orgs.json", help="JSON file listing organisations and their sites")
    ap.add_argument("--org", help="audit only this organisation (by name) from the config file")
    ap.add_argument("--readonly", action="store_true")
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    if not os.path.exists(a.config):
        raise SystemExit(f"{a.config} not found. Copy orgs.example.json to {a.config} and fill in your sites.")
    orgs = load_orgs(a.config)
    if a.org:
        orgs = [o for o in orgs if o["name"] == a.org]
        if not orgs:
            raise SystemExit(f"no organisation named {a.org!r} in {a.config}")
    os.makedirs(a.out, exist_ok=True)
    print(f"Local LLM: {llm.backend_name()}")

    from idt import org_report
    index = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for org in orgs:
            print(f"\n=== {org['name']} ({len(org['sites'])} site(s)) ===")
            before = llm.stats()
            results = []
            for site in org["sites"]:
                url, label = site["url"], site.get("label", site["url"])
                print(f"\n{label} <{url}>")
                try:
                    r = audit(browser, url, readonly=a.readonly)
                except Exception as e:
                    r = {"error": repr(e), "findings": [], "passes": []}
                r.update(name=label, url=url, mode="real" if a.readonly else "audit")
                for f in r["findings"]:
                    print(f"  {f['strength']:<9} {f['ccpa']:<34} {f['title']}")
                results.append(r)
            stats = _diff_stats(before, llm.stats())
            slug = _slug(org["name"])
            json_path = os.path.join(a.out, f"org_{slug}_findings.json")
            html_path = os.path.join(a.out, f"org_{slug}_report.html")
            with open(json_path, "w") as f:
                json.dump(strip({"org": org["name"], "stats": stats, "results": copy.deepcopy(results)}), f, indent=1, default=str)
            org_report.write(html_path, org["name"], results, stats)
            total = sum(len(r.get("findings", [])) for r in results)
            print(f"\n{org['name']}: {total} finding(s) across {len(results)} site(s)")
            print(f"Report: {html_path}")
            index.append((org["name"], os.path.basename(html_path), total, len(results)))
        browser.close()

    if len(index) > 1:
        idx_path = os.path.join(a.out, "org_index.html")
        rows = "".join(f"<tr><td><a href='{p}'>{n}</a></td><td>{t}</td><td>{s}</td></tr>" for n, p, t, s in index)
        with open(idx_path, "w") as f:
            f.write("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
                     "initial-scale=1'><title>Organisation audits</title><body style=\"font:15px system-ui;"
                     "max-width:640px;margin:40px auto;padding:0 16px\"><h1>Organisation audits</h1>"
                     "<table style='border-collapse:collapse;width:100%'><tr style='text-align:left'>"
                     "<th>Organisation</th><th>Findings</th><th>Sites</th></tr>" + rows + "</table></body>")
        print(f"\nIndex: {idx_path}")


if __name__ == "__main__":
    main()
