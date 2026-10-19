"""Self-contained HTML report that rolls up per-site audits into one organisation-level view:
an executive summary (sites scanned, findings by CCPA category and by strength, worst sites first)
followed by the same per-site evidence sections as the single-site report, for drill-down.
"""
import re
from collections import Counter
from datetime import datetime

from .oracles import CCPA
from .templates import ENV

TPL = ENV.from_string(r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dark Pattern Audit — {{ org }}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>
:root{--bg:#f4f5f2;--card:#fff;--ink:#1b1e1c;--mute:#5f6661;--line:#dfe3de;--accent:#a6431f;
 --ok:#2f6f4f;--okbg:#e6f1ea;--bad:#a8321e;--badbg:#f8e8e3;--warn:#7f5a00;--warnbg:#f6eed6;
 --sans:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141715;--card:#1d211e;--ink:#e9ece8;--mute:#a1a8a2;
 --line:#323833;--okbg:#1b3226;--ok:#86c9a2;--badbg:#3a211b;--bad:#f09a84;--warnbg:#383017;--warn:#e3c06a;--accent:#f09a84;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#141715;--card:#1d211e;--ink:#e9ece8;--mute:#a1a8a2;
 --line:#323833;--okbg:#1b3226;--ok:#86c9a2;--badbg:#3a211b;--bad:#f09a84;--warnbg:#383017;--warn:#e3c06a;--accent:#f09a84;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--sans)}
h1,h2,h3{text-wrap:balance}td,.pill,.kpi b{font-variant-numeric:tabular-nums}.kpi b{font-family:var(--mono)}
summary:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.wrap{max-width:1080px;margin:0 auto;padding:32px 16px 64px}.lead,.wrap>p{max-width:72ch}
h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:40px 0 12px;padding-top:8px;border-top:2px solid var(--ink)}
h3{font-size:16px}.sub{color:var(--mute)}.lead{font-size:17px;margin:18px 0 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.kpi b{display:block;font-size:24px}.kpi span{color:var(--mute);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:13.5px}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);font-weight:600}
td.c{text-align:center}.scroll{overflow-x:auto}.scroll>table{min-width:680px}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}
.hit{background:var(--okbg);color:var(--ok)}.miss,.fp{background:var(--badbg);color:var(--bad)}.quiet{color:var(--mute)}
.Proven{background:var(--okbg);color:var(--ok)}.Measured{background:var(--warnbg);color:var(--warn)}.Judged{background:var(--line);color:var(--ink)}
.card{overflow-wrap:anywhere;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:12px 0}
.card h4{margin:0 0 4px;font-size:16px}.meta{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.ccpa{font-size:12px;color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.eo{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:8px 0}.eo>div{min-width:0;overflow-wrap:anywhere;border-left:3px solid var(--line);padding:2px 0 2px 10px}
.eo .o{border-color:var(--accent)}.eo small{display:block;color:var(--mute);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}
ul.ev{margin:6px 0 0;padding-left:18px;overflow-wrap:anywhere}.shots{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
.shots img{width:360px;max-width:100%;border:1px solid var(--line);border-radius:6px}
.method{color:var(--mute);font-size:13px;margin-top:6px}details{margin:8px 0}summary{cursor:pointer;color:var(--mute);font-size:13px}
.site{margin-top:28px}.passes li{margin:3px 0;color:var(--mute)}code{font-family:var(--mono);font-size:13px}
.flow{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:12px 0}
.flow>div{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}.flow b{display:block;margin-bottom:4px}
@media (max-width:640px){.eo{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="sub">Intent-Divergence Testing · organisation audit · {{ when }}</div>
<h1>{{ org }}</h1>
<p class="lead">Audited {{ sites_n }} site{{ '' if sites_n == 1 else 's' }} for India CCPA dark patterns (Guidelines for
Prevention and Regulation of Dark Patterns, 2023), behaviourally and with no site-specific configuration beyond its URL.
{{ clean_sites }} of {{ sites_n }} site{{ '' if sites_n == 1 else 's' }} returned no findings.</p>

<div class="kpis">
<div class="kpi"><b>{{ sites_n }}</b><span>Sites audited</span></div>
<div class="kpi"><b>{{ total }}</b><span>Findings, organisation-wide</span></div>
<div class="kpi"><b>{{ by_strength.get('Proven', 0) }}</b><span>Proven (site contradicted itself)</span></div>
<div class="kpi"><b>{{ by_cat|length }}</b><span>of 13 CCPA categories triggered</span></div>
</div>

{% if errored %}<p class="method"><span class="pill miss">{{ errored|length }} site(s) failed to audit</span> and are excluded
from the counts above — see their entries under Site detail for the error.</p>{% endif %}

<h2>Findings by CCPA category</h2>
<div class="scroll"><table><tr><th>Category</th><th class="c">Findings</th><th>Sites</th></tr>
{% for cat, n in by_cat %}<tr><td>{{ cat }}</td><td class="c">{{ n }}</td>
<td>{% for s in cat_sites[cat] %}<a href="#{{ s.anchor }}">{{ s.name }}</a>{% if not loop.last %}, {% endif %}{% endfor %}</td></tr>{% endfor %}
{% if not by_cat %}<tr><td colspan="3">No dark patterns found across this organisation.</td></tr>{% endif %}
</table></div>

<h2>Sites, worst first</h2>
<div class="scroll"><table><tr><th>Site</th><th class="c">Findings</th><th class="c">Proven</th><th class="c">Measured</th><th class="c">Judged</th></tr>
{% for r in ranked %}<tr><td><a href="#{{ r.anchor }}">{{ r.name }}</a></td><td class="c">{{ r.findings|length }}</td>
<td class="c">{{ r.findings|selectattr('strength','equalto','Proven')|list|length }}</td>
<td class="c">{{ r.findings|selectattr('strength','equalto','Measured')|list|length }}</td>
<td class="c">{{ r.findings|selectattr('strength','equalto','Judged')|list|length }}</td></tr>{% endfor %}
</table></div>

<h2>How it works</h2>
<div class="flow">
<div><b>1 · Discover</b>Each site's home page is read, the pages that matter are visited, and the most promoted product and any paid plan are picked.</div>
<div><b>2 · Walk</b>A careful and a hurried simulated user pursue the same plain-English goal on each site. Both stop before payment.</div>
<div><b>3 · Probe</b>Fresh sessions over time, buying more than the "only N left", refusing cookies, watching for downloads.</div>
<div><b>4 · Judge</b>Each CCPA category is a comparison: choice vs basket, first price vs final, join vs cancel effort.</div></div>
<p>The local model proposes (what a control does, where a price is, what a claim says); fixed code decides. Amounts must
appear verbatim on the page, quotes must be found on the page, and control states are read from the page itself. This
report aggregates independent per-site audits; it does not test behaviour that only emerges across sites (for example,
a single account or purchase journey spanning two properties of the organisation).</p>

<h2>Site detail</h2>
{% import "site_block.html" as sb %}
{% for r in results %}{{ sb.site(r, ccpa) }}{% endfor %}

<h2>Local LLM use</h2>
<div class="scroll"><table><tr><th>Task</th><th>Calls (cached)</th><th>Model time</th></tr>
{% for k, t in stats.by_task.items() %}<tr><td>{{ k }}</td><td>{{ t.calls }} ({{ t.cached }})</td><td>{{ t.seconds }} s</td></tr>{% endfor %}</table></div>
<p class="method">Text model {{ stats.text_model }} · {{ stats.calls }} calls · {{ stats.failures }} failed. Nothing leaves this machine.</p>

<h2>Limits</h2><ul>
<li>Without a site's back end, stock and deadline claims are tested from the outside (quantity probe, fresh sessions). An
inventory feed in UAT makes these checks stronger.</li>
<li>Real public sites are audited read-only: no accounts, no personal data, no subscriptions, never past the payment step.</li>
<li>The hurried user is a risk indicator, not a validated model of real shoppers.</li>
<li>Findings are evidence for legal/compliance review, not legal conclusions. A site with no findings was not proven free
of dark patterns, only that this audit's journeys did not surface one.</li></ul>
</div></body></html>""")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "site"


def write(path: str, org: str, results: list, stats: dict):
    seen = set()
    for r in results:
        base = _slug(r.get("name") or r.get("url") or "site")
        anchor, n = base, 2
        while anchor in seen:
            anchor, n = f"{base}-{n}", n + 1
        seen.add(anchor)
        r["anchor"] = anchor

    ok = [r for r in results if not r.get("error")]
    errored = [r for r in results if r.get("error")]
    all_findings = [(r, f) for r in ok for f in r.get("findings", [])]
    by_cat_count = Counter(f["ccpa"] for _, f in all_findings)
    cat_sites = {}
    for r, f in all_findings:
        cat_sites.setdefault(f["ccpa"], {})[r["anchor"]] = r["name"]
    cat_sites = {cat: [{"anchor": a, "name": n} for a, n in sites.items()] for cat, sites in cat_sites.items()}
    ranked = sorted(ok, key=lambda r: -len(r.get("findings", []))) + errored

    out = TPL.render(
        when=datetime.now().strftime("%d %b %Y %H:%M"), org=org, results=results, ranked=ranked, ccpa=CCPA,
        total=len(all_findings), sites_n=len(results), clean_sites=sum(1 for r in ok if not r.get("findings")),
        by_cat=by_cat_count.most_common(), by_strength=Counter(f["strength"] for _, f in all_findings),
        cat_sites=cat_sites, stats=stats, errored=errored)
    with open(path, "w") as f:
        f.write(out)
