"""Runs one goal-directed journey with one persona in a fresh browser session, records an
evidence trace, and stops at the payment gate (it never presses Pay)."""
import re
import time

from .browser import (observe, shot, dismiss_dialog, click_candidate, set_checkbox, pick_radio,
                      read_kv, PAY_RE, rupees)

FEE_RE = re.compile(r"\+\s*₹\s?([\d,]+)\s*([A-Za-z][A-Za-z ]{0,30})")
MAX_STEPS = 12


def first_seen_price(page, obs) -> dict:
    """What the shopper is told the item costs on the first screen: headline price + any fee shown alongside it."""
    headline = page.evaluate(r"""() => { let best = null, size = 0;
        document.querySelectorAll('main *').forEach(el => { if (el.children.length) return;
          const t = el.innerText || ''; if (!/₹\s?\d/.test(t)) return;
          const f = parseFloat(getComputedStyle(el).fontSize); if (f > size) { size = f; best = t; } });
        return best; }""")
    fees = [{"label": m.group(2).strip().lower(), "amount": int(m.group(1).replace(",", ""))}
            for m in FEE_RE.finditer(obs["text"])]
    return {"price": rupees(headline), "disclosed_fees": fees}


def run_purchase(browser, base: str, product_path: str, account_path: str, persona, intent) -> dict:
    ctx = browser.new_context(viewport={"width": 1100, "height": 760})
    page = ctx.new_page()
    page.goto(base + product_path)
    trace, notes, nags = [], [], 0
    first = None
    reached_gate = False
    gate_obs = None
    for step in range(MAX_STEPS):
        if dismiss_dialog(page):
            nags += 1
        time.sleep(0.2)
        obs = observe(page)
        if first is None:
            first = first_seen_price(page, obs)
        pay = [c for c in obs["candidates"] if PAY_RE.match(c["text"])]
        if pay:
            reached_gate = True
            gate_obs = obs
            trace.append({"step": step, "url": obs["url"], "action": "STOP at payment gate",
                          "detail": f"'{pay[0]['text']}' not pressed (no real transactions)", "shot": shot(page),
                          "candidates": obs["candidates"], "checkboxes": obs["checkboxes"], "text": obs["text"]})
            break
        snap = shot(page)                     # the screen as presented, before this persona acts
        d = persona.decide(obs, intent)
        notes += [dict(n, url=obs["url"]) for n in d.notes]
        acts = []
        for idx, val, why in d.checkbox_changes:
            before = next(c for c in obs["checkboxes"] if c["idx"] == idx)
            if before["checked"] != val:
                acts.append(f"{'tick' if val else 'untick'} '{before['label']}' ({why})")
            set_checkbox(page, idx, val)
        for name in d.radio:
            pick_radio(page, name)
            acts.append(f"answer required question '{name}'")
        if d.click is None:
            trace.append({"step": step, "url": obs["url"], "action": "stuck", "detail": d.click_reason or "no control matches goal",
                          "shot": snap, "candidates": obs["candidates"], "text": obs["text"]})
            break
        chosen = next(c for c in obs["candidates"] if c["idx"] == d.click)
        acts.append(f"click '{chosen['text']}' — {d.click_reason}")
        trace.append({"step": step, "url": obs["url"], "action": "; ".join(acts), "shot": snap,
                      "candidates": obs["candidates"], "checkboxes": obs["checkboxes"], "clicked": chosen,
                      "text": obs["text"]})
        click_candidate(page, d.click)

    rows = gate_obs["rows"] if gate_obs else []
    payable = next((rupees(r[1]) for r in rows if "total" in r[0].lower()), None)
    account = read_kv(page, base, account_path)
    ctx.close()
    return {"persona": persona.name, "trace": trace, "first_seen": first, "gate_rows": rows,
            "gate_text": gate_obs["text"] if gate_obs else "",
            "payable": payable, "account": account, "notes": notes, "nag_dismissals": nags,
            "reached_gate": reached_gate}
