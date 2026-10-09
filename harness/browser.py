"""Page observation helpers shared by every test: what is on screen, how salient it is,
which boxes are ticked, and whether a nag dialog is in the way."""
import base64
import re
import time

# Collected from the page's main content area only (site header/nav is ignored).
OBSERVE_JS = r"""
() => {
  const root = document.querySelector('main') || document.body;
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const sat = el => { const m = getComputedStyle(el).backgroundColor.match(/[\d.]+/g);
    if (!m) return 0; const [r,g,b,a] = m.map(Number); if (a === 0) return 0;
    const mx = Math.max(r,g,b), mn = Math.min(r,g,b); return mx === 0 ? 0 : (mx - mn) / mx + (mx < 90 ? 0.6 : 0); };
  let i = 0; const cands = [];
  root.querySelectorAll('a[href], button, input[type=submit]').forEach(el => {
    if (!vis(el)) return;
    const r = el.getBoundingClientRect(); const fs = parseFloat(getComputedStyle(el).fontSize);
    el.setAttribute('data-dp-idx', String(i));
    const area = r.width * r.height;
    cands.push({idx: i++, tag: el.tagName.toLowerCase(), text: (el.innerText || el.value || '').trim(),
      area: Math.round(area), font: fs, colour: +sat(el).toFixed(2),
      salience: Math.round(area * (1 + 2 * sat(el)) * (fs / 14))});
  });
  let j = 0; const boxes = [];
  root.querySelectorAll('input[type=checkbox]').forEach(el => {
    const lab = el.closest('label'); el.setAttribute('data-dp-cb', String(j));
    boxes.push({idx: j++, name: el.name, checked: el.checked, label: lab ? lab.innerText.trim() : el.name,
      font: lab ? parseFloat(getComputedStyle(lab).fontSize) : 0});
  });
  const radios = {};
  root.querySelectorAll('input[type=radio]').forEach(el => {
    radios[el.name] = radios[el.name] || {name: el.name, required: false, options: []};
    radios[el.name].required = radios[el.name].required || el.required;
    const lab = el.closest('label'); radios[el.name].options.push(lab ? lab.innerText.trim() : el.value);
  });
  const rows = [];
  root.querySelectorAll('tr').forEach(tr => { const c = [...tr.querySelectorAll('td,th')].map(t => t.innerText.trim());
    if (c.length >= 2) rows.push(c); });
  return {url: location.pathname, title: document.title, text: root.innerText, candidates: cands,
          checkboxes: boxes, radios: Object.values(radios), rows: rows};
}
"""

DISMISS_WORDS = ("not now", "no thanks", "close", "maybe later", "skip", "dismiss")
PAY_RE = re.compile(r"^\s*(pay\b|place order|confirm payment|buy now)", re.I)
RUPEE_RE = re.compile(r"₹\s?([\d,]+)")


def rupees(s: str):
    m = RUPEE_RE.search(s or "")
    return int(m.group(1).replace(",", "")) if m else None


def shot(page) -> str:
    """Screenshot cropped to the header + main content, so evidence images are not mostly empty page."""
    box = page.evaluate("() => { const m = document.querySelector('main'); if (!m) return null;"
                        " const r = m.getBoundingClientRect(); return {b: r.bottom + window.scrollY}; }")
    vp = page.viewport_size or {"width": 1100, "height": 760}
    clip = {"x": 0, "y": 0, "width": vp["width"], "height": min(max(box["b"] + 16, 200), vp["height"])} if box else None
    return base64.b64encode(page.screenshot(type="jpeg", quality=60, clip=clip)).decode()


def observe(page) -> dict:
    page.wait_for_load_state("domcontentloaded")
    return page.evaluate(OBSERVE_JS)


def dismiss_dialog(page) -> bool:
    """If a modal dialog covers the page, close it with its dismiss control. Returns True if one was shown."""
    dlg = page.locator("[role=dialog]")
    if dlg.count() == 0 or not dlg.first.is_visible():
        return False
    for el in dlg.first.locator("button, a").all():
        if el.inner_text().strip().lower() in DISMISS_WORDS:
            el.click()
            page.wait_for_load_state("domcontentloaded")
            return True
    return True


def click_candidate(page, idx: int):
    page.locator(f"main [data-dp-idx='{idx}']").first.click()
    page.wait_for_load_state("domcontentloaded")
    time.sleep(0.15)


def set_checkbox(page, idx: int, value: bool):
    el = page.locator(f"main [data-dp-cb='{idx}']").first
    if el.is_checked() != value:
        el.click()


def pick_radio(page, name: str):
    page.locator(f"main input[type=radio][name='{name}']").first.check()


def read_kv(page, path_base: str, path: str) -> dict:
    """Read a label/value table from a system-of-record page (e.g. the account page)."""
    page.goto(path_base + path)
    dismiss_dialog(page)
    obs = observe(page)
    return {r[0]: r[1] for r in obs["rows"]}
