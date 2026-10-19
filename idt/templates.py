"""Shared Jinja macro for rendering one audited site's evidence section, so the single/bench
report (report.py) and the organisation-level report (org_report.py) never drift apart.
"""
from jinja2 import DictLoader, Environment

SITE_BLOCK = r"""
{% macro site(r, ccpa) %}<div class="site"{% if r.anchor %} id="{{ r.anchor }}"{% endif %}><h2>{{ r.name }}</h2>
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
</div>{% endmacro %}
"""

ENV = Environment(loader=DictLoader({"site_block.html": SITE_BLOCK}))
