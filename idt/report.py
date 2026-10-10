"""Self-contained HTML report for generic audits and the benchmark."""
from datetime import datetime

from jinja2 import Template

from .oracles import CCPA

TPL = Template(r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Intent-Divergence Audit</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>
/* Layout: single reading column; matrices and traces scroll inside their own frames */
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
<div class="sub">Intent-Divergence Testing · generic engine · {{ when }}</div>
<h1>Dark Pattern Audit</h1>
{% if scored %}<p class="lead">One engine, no site configuration: it was given only each shop's URL. Across {{ scored|length }} shop variants
(3 structurally different shops, each dark and honest) it found <b>{{ tp }} of {{ tp + fn }}</b> seeded dark patterns covering all 13 CCPA
categories, with <b>{{ fp }}</b> false alarm{{ '' if fp == 1 else 's' }}.{% if injected %} On real third-party sites with
dark patterns injected in the browser it found <b>{{ itp }} of {{ itp + ifn }}</b> with <b>{{ ifp }}</b> false alarm{{ '' if ifp == 1 else 's' }}.{% endif %}{% if real %} It also audited {{ real|length }} real public test shops read-only.{% endif %}</p>
<div class="kpis"><div class="kpi"><b>{{ tp }}/{{ tp + fn }}</b><span>Seeded patterns found</span></div>
<div class="kpi"><b>{{ fp }}</b><span>False alarms (incl. honest shops)</span></div>
<div class="kpi"><b>0</b><span>Lines of site-specific configuration</span></div>
<div class="kpi"><b>{{ stats.calls }}</b><span>Local LLM calls ({{ stats.text_model }})</span></div></div>
{% else %}<p class="lead">Audited {{ results|length }} site(s) with no site configuration.</p>{% endif %}

<h2>How it works</h2>
<div class="flow">
<div><b>1 · Discover</b>Reads the home page, visits the pages that matter, and picks the most promoted product and any paid plan.</div>
<div><b>2 · Walk</b>A careful and a hurried simulated user pursue the same plain-English goal. Both stop before payment.</div>
<div><b>3 · Probe</b>Fresh sessions over time, buying more than the "only N left", refusing cookies, watching for downloads.</div>
<div><b>4 · Judge</b>Each CCPA category is a comparison: choice vs basket, first price vs final, join vs cancel effort.</div></div>
<p>The local model proposes (what a control does, where a price is, what a claim says); fixed code decides. Amounts must
appear verbatim on the page, quotes must be found on the page, and control states are read from the page itself.</p>

{% if scored %}<h2>Scorecard</h2>
<div class="scroll"><table><tr><th>CCPA category</th>{% for r in scored + injected %}<th class="c">{{ r.shop }}<br>{{ modes[r.mode] }}</th>{% endfor %}</tr>
{% for k, lab in ccpa.items() %}<tr><td>{{ lab }}</td>{% for r in scored + injected %}<td class="c">
{% if k in r.tp %}<span class="pill hit">found</span>{% elif k in r.fn %}<span class="pill miss">missed</span>
{% elif k in r.fp %}<span class="pill fp">false alarm</span>{% else %}<span class="quiet">·</span>{% endif %}</td>{% endfor %}</tr>{% endfor %}
</table></div>
<p class="method">"·" means the pattern was not seeded or injected there and the engine correctly reported nothing.
{% if injected %}The last {{ injected|length }} columns are real third-party sites with dark patterns injected in our own browser
({{ itp }} of {{ itp + ifn }} found, {{ ifp }} false alarm{{ '' if ifp == 1 else 's' }}); "honest" adds non-deceptive look-alikes and
"as is" is the unmodified site.{% endif %}</p>{% endif %}

{% for r in results %}<div class="site"><h2>{{ r.name }}</h2>
{% if r.error %}<p><span class="pill miss">audit error</span> {{ r.error }}</p>{% endif %}
<p class="method">Plan: {% for j in r.journeys_planned or [] %}{{ j.type }}{% if j.product %} '{{ j.product }}'{% endif %}{% if j.plan %} '{{ j.plan }}'{% endif %}{% if not loop.last %} · {% endif %}{% endfor %}
{% if r.seconds %} · {{ r.seconds }} s{% endif %}{% if r.mode == 'real' %} · read-only{% endif %}</p>
{% for f in r.findings %}<div class="card"><div class="meta"><span class="ccpa">{{ f.ccpa }}</span><span class="pill {{ f.strength }}">{{ f.strength }}</span>
{% if r.truth is defined and r.mode != 'real' %}{% if f.key in r.tp %}<span class="pill hit">seeded</span>{% else %}<span class="pill fp">not seeded</span>{% endif %}{% endif %}</div>
<h4>{{ f.title|replace('_', ' ') }}</h4><div class="eo"><div><small>Expected</small>{{ f.expected }}</div><div class="o"><small>Observed</small>{{ f.observed }}</div></div>
<ul class="ev">{% for e in f.evidence %}<li>{{ e }}</li>{% endfor %}</ul><div class="method">Method: {{ f.method }}</div>
{% if f.shots %}<div class="shots">{% for s in f.shots %}<img alt="Evidence screenshot" src="data:image/jpeg;base64,{{ s }}">{% endfor %}</div>{% endif %}</div>
{% else %}<p>No findings.</p>{% endfor %}
{% if r.fn %}<p><span class="pill miss">missed</span> {% for k in r.fn %}{{ ccpa[k] }}{% if not loop.last %}, {% endif %}{% endfor %}</p>{% endif %}
<details><summary>Checks that passed ({{ r.passes|length }})</summary><ul class="passes">{% for p in r.passes %}<li>{{ p }}</li>{% endfor %}</ul></details>
{% for grp in ['purchase', 'subscription'] %}{% if r[grp] %}{% for who, j in r[grp].items() %}
<details><summary>{{ grp }} · {{ who }} · {{ j.trace|length }} screens · ended: {{ j.reached }}</summary>
<p class="method">Goal: {{ j.intent }}</p><div class="scroll"><table><tr><th>#</th><th>Screen</th><th>Kind</th><th>What the user did</th></tr>
{% for s in j.trace %}<tr><td>{{ s.step + 1 }}</td><td style="overflow-wrap:anywhere">{{ s.url }}</td><td>{{ s.page_kind }}</td><td>{{ s.actions|join('; ') }}</td></tr>{% endfor %}
</table></div></details>{% endfor %}{% endif %}{% endfor %}
</div>{% endfor %}

<h2>Local LLM use</h2>
<div class="scroll"><table><tr><th>Task</th><th>Calls (cached)</th><th>Model time</th></tr>
{% for k, t in stats.by_task.items() %}<tr><td>{{ k }}</td><td>{{ t.calls }} ({{ t.cached }})</td><td>{{ t.seconds }} s</td></tr>{% endfor %}</table></div>
<p class="method">Text model {{ stats.text_model }} · {{ stats.calls }} calls · {{ stats.failures }} failed. Nothing leaves this machine.</p>

<h2>Limits</h2><ul>
<li>The test shops were written alongside the engine. They differ in structure, wording, currency and mechanism, but they are not
independent of it; the real-site runs are the check on that.</li>
<li>Without a site's back end, stock and deadline claims are tested from the outside (quantity probe, fresh sessions). An inventory
feed in UAT makes these checks stronger.</li>
<li>Real public sites are audited read-only: no accounts, no personal data, no subscriptions, never past the payment step.</li>
<li>The hurried user is a risk indicator, not a validated model of real shoppers. Findings are evidence for legal review.</li></ul>
</div></body></html>""")


def write(path, results, stats):
    scored = [r for r in results if r.get("mode") in ("dark", "clean")]
    real = [r for r in results if r.get("mode") == "real"]
    injected = [r for r in results if str(r.get("mode", "")).startswith("injected")]
    out = TPL.render(when=datetime.now().strftime("%d %b %Y %H:%M"), results=results, scored=scored, real=real, stats=stats,
                     ccpa=CCPA, tp=sum(len(r["tp"]) for r in scored), fn=sum(len(r["fn"]) for r in scored),
                     fp=sum(len(r["fp"]) for r in scored), injected=injected,
                     itp=sum(len(r["tp"]) for r in injected), ifn=sum(len(r["fn"]) for r in injected),
                     ifp=sum(len(r["fp"]) for r in injected),
                     modes={"dark": "dark", "clean": "honest", "injected-dark": "injected", "injected-honest": "honest look-alikes",
                            "injected-clean": "as is"})
    with open(path, "w") as f:
        f.write(out)
