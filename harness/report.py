"""Self-contained HTML evidence report (screenshots embedded)."""
import html
from datetime import datetime

from jinja2 import Template

from .oracles import CCPA

TPL = Template(r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dark Pattern Evidence Report</title>
<style>
:root{--bg:#f7f6f3;--card:#fff;--ink:#1c1c1c;--mute:#6b6b6b;--line:#e4e2dc;--accent:#b4441f;
 --ok:#2f6f4f;--okbg:#e8f2ec;--bad:#a8321e;--badbg:#f8e9e5;--warn:#8a6100;--warnbg:#f7efd9}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecebe7;--mute:#a09f99;--line:#34332f;
 --okbg:#1d3328;--ok:#7fc49c;--badbg:#3a211b;--bad:#f09a84;--warnbg:#3a3019;--warn:#e3c06a;--accent:#f09a84}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Inter",system-ui,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:19px;margin:40px 0 12px;padding-top:8px;border-top:2px solid var(--ink)}
.sub{color:var(--mute)}.lead{font-size:17px;margin:18px 0 0;max-width:760px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.kpi b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.kpi span{color:var(--mute);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top;font-size:14px}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);font-weight:600}
td.c{text-align:center}.scroll{overflow-x:auto}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}
.hit{background:var(--okbg);color:var(--ok)}.miss{background:var(--badbg);color:var(--bad)}
.fp{background:var(--badbg);color:var(--bad)}.quiet{color:var(--mute)}
.Proven{background:var(--okbg);color:var(--ok)}.Measured{background:var(--warnbg);color:var(--warn)}.Judged{background:var(--line);color:var(--ink)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}
.card h3{margin:0 0 4px;font-size:17px}.meta{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.ccpa{font-size:12px;color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.eo{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0}
.eo div{border-left:3px solid var(--line);padding:2px 0 2px 10px}.eo .o{border-color:var(--accent)}
.eo small{display:block;color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
ul.ev{margin:6px 0 0;padding-left:18px}ul.ev li{margin:2px 0}
.shots{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.shots img{width:380px;max-width:100%;border:1px solid var(--line);border-radius:6px}
.method{color:var(--mute);font-size:13px;margin-top:8px}
.ok li{margin:4px 0}.trace td{font-size:13px}
details{margin-top:10px}summary{cursor:pointer;color:var(--mute);font-size:13px}
@media (max-width:640px){.eo{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="sub">Intent-Divergence Testing · proof of concept · {{ when }}</div>
<h1>Dark Pattern Evidence Report</h1>
<p class="lead">Behavioural testing found <b>{{ h_dark }} of {{ n_seed }}</b> seeded dark patterns in the test shop with
<b>{{ h_fp }}</b> false alarms on the honest control. A single-screen recognition baseline found {{ b_dark }} of {{ n_seed }}
and raised {{ b_fp }} false alarms on the control.{% if has_vlm %} A local vision-language model ({{ stats.vision_model }})
judging each screenshot on its own found {{ v_dark }} of {{ n_seed }} and raised {{ v_fp }} false alarms.{% endif %}</p>
<div class="kpis">
 <div class="kpi"><b>{{ h_dark }}/{{ n_seed }}</b><span>Seeded patterns detected (this harness)</span></div>
 <div class="kpi"><b>{{ h_fp }}</b><span>False alarms on honest control</span></div>
 <div class="kpi"><b>{{ b_dark }}/{{ n_seed }}</b><span>Detected by lexical single-screen baseline</span></div>
 <div class="kpi"><b>{{ b_fp }}</b><span>Lexical baseline false alarms on control</span></div>
{% if has_vlm %} <div class="kpi"><b>{{ v_dark }}/{{ n_seed }} · {{ v_fp }} FP</b><span>Screenshot-VLM baseline (detected · false alarms)</span></div>{% endif %}
</div>

<h2>Scorecard</h2>
<div class="scroll"><table><tr><th>Seeded pattern</th><th>CCPA category</th><th class="c">Harness · dark shop</th>
<th class="c">Harness · honest shop</th><th class="c">Lexical baseline · dark</th><th class="c">Lexical baseline · honest</th>
{% if has_vlm %}<th class="c">VLM baseline · dark</th><th class="c">VLM baseline · honest</th>{% endif %}</tr>
{% for r in score %}<tr><td>{{ r.desc }}</td><td>{{ r.ccpa }}</td>
<td class="c">{% if r.h_dark %}<span class="pill hit">detected</span>{% else %}<span class="pill miss">missed</span>{% endif %}</td>
<td class="c">{% if r.h_clean %}<span class="pill fp">false alarm</span>{% else %}<span class="quiet">clean</span>{% endif %}</td>
<td class="c">{% if r.b_dark %}<span class="pill hit">detected</span>{% else %}<span class="pill miss">missed</span>{% endif %}</td>
<td class="c">{% if r.b_clean %}<span class="pill fp">false alarm</span>{% else %}<span class="quiet">clean</span>{% endif %}</td>
{% if has_vlm %}<td class="c">{% if r.v_dark %}<span class="pill hit">detected</span>{% else %}<span class="pill miss">missed</span>{% endif %}</td>
<td class="c">{% if r.v_clean %}<span class="pill fp">false alarm</span>{% else %}<span class="quiet">clean</span>{% endif %}</td>{% endif %}</tr>{% endfor %}
</table></div>
<p class="method">The honest shop shows real urgency (one fixed sale deadline) and real scarcity (stock that matches inventory),
discloses its delivery fee up front, offers Plus neutrally and lets you cancel in two clicks.</p>

<h2>Findings · {{ dark.name }}</h2>
{% for f in dark.findings %}<div class="card">
 <div class="meta"><span class="ccpa">{{ f.ccpa }}</span><span class="pill {{ f.strength }}">{{ f.strength }}</span></div>
 <h3>{{ f.title }}</h3>
 <div class="eo"><div><small>Expected</small>{{ f.expected }}</div><div class="o"><small>Observed</small>{{ f.observed }}</div></div>
 <ul class="ev">{% for e in f.evidence %}<li>{{ e }}</li>{% endfor %}</ul>
 <div class="method">Method: {{ f.method }}</div>
 {% if f.shots %}<div class="shots">{% for s in f.shots %}<img alt="Evidence screenshot" src="data:image/jpeg;base64,{{ s }}">{% endfor %}</div>{% endif %}
</div>{% endfor %}

<h2>Manipulation delta · same goal, different attention</h2>
<p>Every persona was told: <i>{{ intent }}</i>. Anything the hurried user ends up with that the careful user avoided
is what the interface extracts from inattention.{% if dark.agent %} The <b>agent</b> persona is a local LLM navigating from that
sentence alone, with no site-specific goal words.{% endif %}</p>
<div class="scroll"><table><tr><th>Outcome</th>{% for shop in [dark, clean] %}{% for p in shop.delta.payable %}<th>{{ shop.name }} · {{ p }}</th>{% endfor %}{% endfor %}</tr>
{% for k, lab in delta_rows %}<tr><td>{{ lab }}</td>
{% for shop in [dark, clean] %}{% for p in shop.delta.payable %}<td>{{ fmt(shop.delta[k][p]) }}</td>{% endfor %}{% endfor %}</tr>{% endfor %}
</table></div>

<h2>Friction and falsity measurements</h2>
<div class="scroll"><table><tr><th>Check</th><th>{{ dark.name }}</th><th>{{ clean.name }}</th></tr>
<tr><td>Join Plus (actions)</td><td>{{ dark.fric.join.actions }}</td><td>{{ clean.fric.join.actions }}</td></tr>
<tr><td>Cancel Plus (actions)</td><td>{{ dark.fric.cancel.actions }}</td><td>{{ clean.fric.cancel.actions }}</td></tr>
<tr><td>Cancel ÷ join</td><td>{{ dark.fric.ratio }}×</td><td>{{ clean.fric.ratio }}×</td></tr>
{% if dark.fric.agent %}<tr><td>LLM agent, plain-English goal: join / cancel actions</td>
<td>{{ dark.fric.agent.join.actions }} / {{ dark.fric.agent.cancel.actions }}{% if not dark.fric.agent.cancel.completed %} (did not finish){% endif %} · {{ dark.fric.agent.ratio }}×</td>
<td>{{ clean.fric.agent.join.actions }} / {{ clean.fric.agent.cancel.actions }}{% if not clean.fric.agent.cancel.completed %} (did not finish){% endif %} · {{ clean.fric.agent.ratio }}×</td></tr>{% endif %}
<tr><td>Countdown deadline spread across sessions</td><td>{{ dark.fals.timer.deadline_spread_s }} s</td><td>{{ clean.fals.timer.deadline_spread_s }} s</td></tr>
<tr><td>Claims read by</td><td>{{ dark.fals.observations[0].extracted_by }}</td><td>{{ clean.fals.observations[0].extracted_by }}</td></tr>
<tr><td>Stock claim vs inventory</td><td>{{ dark.fals.stock.claim }} vs {{ dark.fals.stock.inventory }}</td><td>{{ clean.fals.stock.claim }} vs {{ clean.fals.stock.inventory }}</td></tr>
<tr><td>Nag reappearances after dismissal</td><td>{{ dark.nag.reappeared_on|length }} / {{ dark.nag.pages_after_dismissal }}</td><td>{{ clean.nag.reappeared_on|length }} / {{ clean.nag.pages_after_dismissal }}</td></tr>
</table></div>

<h2>Honest control · {{ clean.name }}</h2>
{% if clean.findings %}<p><b>{{ clean.findings|length }} finding(s) raised on the control — review:</b> {% for f in clean.findings %}{{ f.ccpa }}{% if not loop.last %}, {% endif %}{% endfor %}</p>{% else %}
<p>No findings. Checks that passed:</p>{% endif %}
<ul class="ok">{% for p in clean.passes %}<li>{{ p }}</li>{% endfor %}</ul>

<h2>Baseline detections</h2>
<div class="scroll"><table><tr><th>Shop</th><th>Category</th><th>Why the baseline flagged it</th></tr>
{% for shop in [dark, clean] %}{% for k, why in shop.base.items() %}<tr><td>{{ shop.name }}</td><td>{{ ccpa[k] }}</td><td>{{ why|join('; ') }}</td></tr>{% endfor %}{% endfor %}
</table></div>

{% if has_vlm %}<h2>Screenshot-VLM baseline detections</h2>
<p class="method">{{ stats.vision_model }} saw each distinct screen once, with the CCPA category definitions, and no other context.</p>
<div class="scroll"><table><tr><th>Shop</th><th>Category</th><th>What the VLM said it saw</th></tr>
{% for shop in [dark, clean] %}{% for k, why in shop.vlm.items() %}<tr><td>{{ shop.name }}</td><td>{{ ccpa[k] }}</td><td>{{ why|join('; ') }}</td></tr>{% endfor %}{% endfor %}
</table></div>{% endif %}

<h2>Where the local LLM is used</h2>
<p>The model <b>proposes</b>; a deterministic oracle <b>disposes</b>. No verdict on price, order contents, membership,
consent state, stock or click counts depends on model output, and no screen leaves this machine.</p>
<div class="scroll"><table><tr><th>Task</th><th>What the model does</th><th>What keeps it honest</th><th>Calls (cached)</th><th>Model time</th></tr>
{% for task, why, guard in llm_uses %}{% set t = stats.by_task.get(task) %}<tr><td>{{ task }}</td><td>{{ why }}</td><td>{{ guard }}</td>
<td>{% if t %}{{ t.calls }} ({{ t.cached }}){% else %}—{% endif %}</td><td>{% if t %}{{ t.seconds }} s{% else %}—{% endif %}</td></tr>{% endfor %}
</table></div>
{% for shop in [dark, clean] %}{% if shop.agent %}<p>LLM navigator on {{ shop.name }}: {% if shop.agent.agrees %}<span class="pill hit">same end state as scripted careful persona</span>
{% else %}<span class="pill miss">differs on {{ shop.agent.diff|join(', ') }}</span>{% endif %}</p>{% endif %}{% endfor %}
<p class="method">Text model: {{ stats.text_model or 'none' }} · vision model: {{ stats.vision_model or 'none' }} ·
{{ stats.calls }} calls, {{ stats.cached }} from cache, {{ stats.failures }} failed (fell back to heuristics).</p>

<h2>Journey traces</h2>
{% for shop in [dark, clean] %}{% for j in shop.journeys %}
<details><summary>{{ shop.name }} · {{ j.persona }} persona · {{ j.trace|length }} steps · payable ₹{{ j.payable }}</summary>
<table class="trace"><tr><th>#</th><th>Screen</th><th>What the persona did</th></tr>
{% for s in j.trace %}<tr><td>{{ s.step + 1 }}</td><td>{{ s.url }}</td><td>{{ s.action }}{% if s.detail %} — {{ s.detail }}{% endif %}</td></tr>{% endfor %}
</table></details>{% endfor %}{% endfor %}

<h2>Method and limits</h2>
<ul>
<li>Pass/fail is decided by deterministic oracles (order contents, prices, account state, inventory, click counts). Model-assisted steps use: <b>{{ backend }}</b>; wording judgements are marked “Judged” for human review.</li>
<li>The hurried persona is a risk indicator, not a validated model of real shoppers. Calibrate it against session data before quoting it as user harm.</li>
<li>Journeys stop at the payment gate; nothing is purchased. Run against UAT or staging with test accounts.</li>
<li>Findings are evidence for legal review, not legal conclusions.</li>
<li>The scarcity check needs the client’s inventory system of record; without it, stock claims are reported as unverified.</li>
</ul>
</div></body></html>""")


def fmt(v):
    return "—" if v is None else (f"₹{v}" if isinstance(v, int) else v)


LLM_USES = [
    ("navigation", "Agent persona chooses checkboxes and clicks from the plain-English intent",
     "End state read from the order and the account system of record, not from the model"),
    ("claim extraction", "Finds urgency / scarcity claims however they are phrased",
     "Quotes must appear verbatim on the page; deadline arithmetic and inventory comparison are deterministic"),
    ("consent wording", "Works out what ticking a consent box means", "Consent outcome read from account state"),
    ("confirm-shaming wording", "Judges decline copy shown next to an offer", "Reported as “Judged”, for human review"),
    ("VLM screenshot baseline", "Comparison only: what a state-of-the-art screenshot model would flag",
     "Not used for any harness finding"),
]


def write(path, dark, clean, score, backend, intent, has_vlm=False, stats=None):
    def count(key):
        return sum(1 for r in score if r[key])
    out = TPL.render(
        when=datetime.now().strftime("%d %b %Y %H:%M"), dark=dark, clean=clean, score=score, backend=backend,
        intent=intent, ccpa=CCPA, fmt=fmt, n_seed=len(score),
        h_dark=count("h_dark"), h_fp=len(clean["findings"]), b_dark=count("b_dark"), b_fp=len(clean["base"]),
        has_vlm=has_vlm, v_dark=count("v_dark"), v_fp=len(clean["vlm"] or {}), llm_uses=LLM_USES,
        stats=stats or {"by_task": {}, "calls": 0, "cached": 0, "failures": 0},
        delta_rows=[("payable", "Payable at payment gate"), ("addons", "Unrequested add-ons"),
                    ("membership", "Membership after journey"), ("recurring", "Recurring charge"),
                    ("consent", "Partner data sharing")])
    with open(path, "w") as f:
        f.write(out)
