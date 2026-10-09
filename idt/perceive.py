"""Site-agnostic perception: what is on the screen, how prominent each control is, which popups cover the
page, what state each form control is in, and what the page did on its own (downloads, redirects, dialogs).

Works from the DOM of any page. Nothing here knows any site's labels, routes or markup conventions.
"""
import base64
import re
import time
from urllib.parse import urlparse

SNAPSHOT_JS = r"""
() => {
  const vw = innerWidth, vh = innerHeight;
  const txt = s => (s || '').replace(/\s+/g, ' ').trim();
  const vis = el => { const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el); return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.05; };
  const sat = el => { for (let a = el, i = 0; a && i < 3; a = a.parentElement, i++) {
      const m = getComputedStyle(a).backgroundColor.match(/[\d.]+/g); if (!m) continue;
      const [r, g, b, al = 1] = m.map(Number); if (al === 0) continue;
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b); return mx === 0 ? 0.6 : (mx - mn) / mx + (mx < 90 ? 0.6 : 0); }
    return 0; };

  // popups and banners: outermost visible fixed elements that are large or span the screen edge
  const overlays = [];
  document.querySelectorAll('body *').forEach(el => {
    const s = getComputedStyle(el); if (s.position !== 'fixed' || !vis(el)) return;
    if (el.parentElement && el.parentElement.closest('[data-idt-ov]')) return;
    const tag = el.tagName.toLowerCase(), role = el.getAttribute('role') || '';
    if (tag === 'header' || tag === 'nav' || role === 'banner' || role === 'navigation') return;
    const r = el.getBoundingClientRect(); const area = (Math.min(r.right, vw) - Math.max(r.left, 0)) * (Math.min(r.bottom, vh) - Math.max(r.top, 0));
    const big = area > 0.12 * vw * vh, edge = r.width > 0.6 * vw && r.height > 40;
    const box = area > 0.025 * vw * vh && el.querySelector('button, a[href], input');   // corner popups and slide-ins
    const t = txt(el.innerText); if (!(big || edge || box) || t.length < 3) return;
    el.setAttribute('data-idt-ov', String(overlays.length));
    overlays.push({idx: overlays.length, text: t.slice(0, 500), cover: +(area / (vw * vh)).toFixed(2)});
  });

  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], ' +
              '[role=switch], [role=radio], [role=menuitem], [role=tab], summary';
  const region = el => { const o = el.closest('[data-idt-ov]'); if (o) return 'popup#' + o.getAttribute('data-idt-ov');
    for (let a = el; a; a = a.parentElement) { const t = a.tagName.toLowerCase(), r = a.getAttribute('role');
      if (t === 'footer' || r === 'contentinfo') return 'footer';
      if (t === 'nav' || t === 'header' || r === 'navigation' || r === 'banner') return 'nav'; }
    return 'main'; };
  const nameOf = el => { let n = el.getAttribute('aria-label') || '';
    if (!n && el.getAttribute('aria-labelledby')) n = el.getAttribute('aria-labelledby').split(/\s+/).map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    if (!n && el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) n = l.innerText; }
    if (!n) { const l = el.closest('label'); if (l) n = l.innerText; }
    if (!n && (el.type === 'checkbox' || el.type === 'radio')) n = el.parentElement ? el.parentElement.innerText : '';
    if (!n) n = el.innerText || (['submit', 'button'].includes(el.type) ? el.value : '') || el.placeholder || el.title ||
               el.getAttribute('alt') || ((el.querySelector && el.querySelector('img')) || {}).alt || el.name || '';
    return txt(n).slice(0, 140); };
  const kindOf = el => { const t = el.tagName.toLowerCase(), ty = (el.type || '').toLowerCase(), r = el.getAttribute('role');
    if (t === 'a' || r === 'link' || r === 'menuitem' || r === 'tab') return 'link';
    if (t === 'select') return 'select'; if (t === 'textarea') return 'text';
    if (t === 'input') { if (ty === 'checkbox') return 'checkbox'; if (ty === 'radio') return 'radio';
      if (['submit', 'button', 'reset', 'image'].includes(ty)) return 'button'; if (ty === 'number') return 'number'; return 'text'; }
    if (r === 'checkbox' || r === 'switch') return 'checkbox'; if (r === 'radio') return 'radio'; return 'button'; };
  const MONEY = /(₹|rs\.?|inr|\$|usd|€|eur|£|gbp)\s?\d|\d[\d.,]*\s?(€|eur|usd|inr)/i;
  const context = el => { for (let a = el, i = 0; a && i < 6; a = a.parentElement, i++) { const t = txt(a.innerText);
      if (t.length > 350) break; if (MONEY.test(t)) return t; } return ''; };

  const els = []; let n = 0;
  document.querySelectorAll('[data-idt]').forEach(e => e.removeAttribute('data-idt'));
  document.querySelectorAll(SEL).forEach(el => {
    const k = kindOf(el);
    const shown = vis(el) || ((k === 'checkbox' || k === 'radio') && el.closest('label') && vis(el.closest('label')));
    if (!shown || el.disabled) return;
    if (el.parentElement && el.parentElement.closest('a[href], button')) return;
    const id = 'e' + (n++); el.setAttribute('data-idt', id);
    const r = (vis(el) ? el : el.closest('label')).getBoundingClientRect();
    const fs = parseFloat(getComputedStyle(el).fontSize) || 14;
    const href = el.href && typeof el.href === 'string' ? el.href : '';
    let offsite = false; try { offsite = !!href && /^https?:/.test(href) && new URL(href).origin !== location.origin; } catch (e) {}
    const checked = (k === 'checkbox' || k === 'radio') ? (el.checked !== undefined ? !!el.checked : el.getAttribute('aria-checked') === 'true') : null;
    els.push({id, kind: k, name: nameOf(el), region: region(el), checked, required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      value: (k === 'text' || k === 'number' || k === 'select') ? txt(el.value).slice(0, 60) : null,
      group: k === 'radio' ? (el.name || '') : null, href, offsite,
      question: k === 'radio' ? txt(((el.closest('fieldset, [role=radiogroup]') || (el.parentElement && el.parentElement.parentElement) || el).innerText) || '').slice(0, 220) : null,
      options: k === 'select' ? [...el.options].slice(0, 12).map(o => txt(o.text)) : null,
      autocomplete: el.getAttribute('autocomplete') || '', field: txt((el.name || '') + ' ' + (el.id || '') + ' ' + (el.placeholder || '')).slice(0, 60),
      context: (k === 'link' || k === 'button') ? context(el) : '',
      salience: Math.round(Math.min(r.width * r.height, vw * vh / 4) * (1 + 2 * sat(el)) * (fs / 14))});
  });
  const pay = els.some(e => /cc-|card.?num|cvc|cvv|expir/i.test(e.autocomplete + ' ' + e.field)) ||
    [...document.querySelectorAll('iframe')].some(f => /stripe|braintree|adyen|razorpay|paypal|checkout\.com|payu/i.test(f.src || ''));
  return {url: location.href, title: document.title, text: txt(document.body ? document.body.innerText : '').slice(0, 7000),
          overlays, elements: els, payment_fields: pay};
}
"""

# A control whose activation would take money or place an order. The engine never activates one.
PAY_RE = re.compile(r"^\s*(pay\b|pay now|place (my )?order|complete (order|purchase|payment)|confirm (and pay|order|payment|purchase)|"
                    r"submit order|buy and pay|proceed to pay(ment)?$|make payment|authori[sz]e payment)", re.I)
# Additionally blocked on real sites (read-only mode): anything that creates an account or a commitment.
COMMIT_RE = re.compile(r"\b(sign ?up|register|create (an )?account|subscribe|start (my |your )?(free )?trial|join|log ?in|sign ?in)\b", re.I)
DOWNLOAD_EXT = re.compile(r"\.(exe|msi|dmg|pkg|apk|bat|cmd|scr|vbs|jar|ps1|sh|bin|zip|rar)$", re.I)


# Like a browser's autofill: fill empty text fields of the form being submitted from the test profile, by field type.
# Never touches card fields, checkboxes, radios or anything already filled.
AUTOFILL_JS = r"""([id, p]) => { const b = document.querySelector('[data-idt="' + id + '"]'); const f = b && b.closest('form');
  if (!f) return []; const out = [];
  const set = (e, v) => { const d = Object.getOwnPropertyDescriptor(e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype :
    HTMLInputElement.prototype, 'value'); d.set.call(e, v); e.dispatchEvent(new Event('input', {bubbles: true}));
    e.dispatchEvent(new Event('change', {bubbles: true})); };
  for (const e of f.querySelectorAll('input, textarea')) {
    if (e.value || ['hidden', 'checkbox', 'radio', 'submit', 'button', 'file', 'number', 'range', 'date'].includes(e.type) ||
        e.getBoundingClientRect().width === 0) continue;
    const l = e.closest('label') || (e.id && document.querySelector('label[for="' + e.id + '"]'));
    const k = [e.getAttribute('autocomplete'), e.type, e.name, e.id, e.placeholder, l && l.innerText].join(' ').toLowerCase();
    if (/cc-|card|cvv|cvc|expir|coupon|promo|search/.test(k)) continue;
    const v = /email/.test(k) ? p.email : /password/.test(k) ? p.password : /zip|postal|post ?code|pin ?code/.test(k) ? p.zip :
      /phone|tel|mobile/.test(k) ? p.phone : /city|town/.test(k) ? p.city : /state|region|province/.test(k) ? p.state :
      /address|street|addr/.test(k) ? p.address : /first/.test(k) ? p.first : /last|surname/.test(k) ? p.last :
      /name/.test(k) ? p.name : /country/.test(k) ? p.country : (e.required ? 'Test' : null);
    if (v != null) { set(e, v); out.push((l && l.innerText || e.name || e.type).replace(/\s+/g, ' ').trim().slice(0, 30)); } }
  return out; }"""
AUTOFILL = {"email": "idt.audit@example.com", "password": "Audit#2026xq", "zip": "560001", "phone": "9876543210",
            "city": "Bengaluru", "state": "Karnataka", "address": "12 MG Road", "first": "Test", "last": "User",
            "name": "Test User", "country": "India"}


# Callables run on every new browser context the engine opens (e.g. a test fixture that injects scripts).
# The engine itself registers none.
CONTEXT_HOOKS = []

MARK_JS = r"""(on) => { document.querySelectorAll('.__idt_mark').forEach(m => m.remove()); if (!on) return [];
  const vw = innerWidth, vh = innerHeight, shown = [];
  document.querySelectorAll('[data-idt]').forEach(el => { const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) return;
    const id = el.getAttribute('data-idt'); shown.push(id);
    const m = document.createElement('div'); m.className = '__idt_mark';
    m.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;` +
      'outline:2px solid #e00;z-index:2147483647;pointer-events:none;';
    const t = document.createElement('span'); t.textContent = id;
    t.style.cssText = 'position:absolute;left:0;top:-14px;background:#e00;color:#fff;font:bold 11px monospace;padding:0 2px';
    m.appendChild(t); document.documentElement.appendChild(m); });
  return shown; }"""


def origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


class Tab:
    """One browser context + page with monitors for what the site does without being asked."""

    def __init__(self, browser, start_url: str, readonly: bool = False):
        self.ctx = browser.new_context(viewport={"width": 1280, "height": 860}, accept_downloads=True,
                                       user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                                  "Chrome/131.0 Safari/537.36 IDT-audit")
        for hook in CONTEXT_HOOKS:
            hook(self.ctx)
        self.page = self.ctx.new_page()
        self.origin = origin(start_url)
        self.json = []            # JSON the page itself downloaded (its own data: stock, prices, deadlines)
        self.page.on("response", self._response)
        self.readonly = readonly
        self.events = []          # downloads, popups, offsite navigations, JS dialogs
        self.last_action = 0.0
        self.last_click = ("", "")     # (href, name) of the last control clicked by a persona
        self.autofilled = []
        self.page.on("dialog", self._dialog)
        self.page.on("download", self._download)
        self.ctx.on("page", self._popup)
        self.page.on("framenavigated", self._nav)

    def _user(self):
        return time.time() - self.last_action < 2.0

    def _response(self, r):
        try:
            if len(self.json) < 60 and r.request.resource_type in ("xhr", "fetch") and "json" in (r.headers.get("content-type") or ""):
                self.json.append({"url": r.url, "body": r.text()[:200000], "page": self.page.url})
        except Exception:
            pass

    def marked_shot(self):
        """Screenshot with every visible control outlined and labelled by its id (set-of-marks), for a vision model."""
        try:
            shown = self.page.evaluate(MARK_JS, True)
            img = self.shot()
        finally:
            try:
                self.page.evaluate(MARK_JS, False)
            except Exception:
                pass
        return img, shown

    def _dialog(self, d):
        self.events.append({"type": "js_dialog", "kind": d.type, "message": d.message[:300], "url": self.page.url})
        try:
            d.accept() if d.type == "alert" else d.dismiss()
        except Exception:
            pass

    def _download(self, dl):
        href, name = self.last_click
        asked = (bool(href) and dl.url.split("#")[0] == href.split("#")[0]) or bool(re.search(r"download|install|get the app", name, re.I))
        self.events.append({"type": "download", "url": dl.url, "file": dl.suggested_filename, "after_user_action": asked,
                            "page": self.page.url, "executable": bool(DOWNLOAD_EXT.search(dl.suggested_filename or ""))})
        try:
            dl.cancel()
        except Exception:
            pass

    def _popup(self, p):
        if p is self.page:
            return
        try:
            p.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        self.events.append({"type": "new_window", "url": p.url, "after_user_action": self._user(), "page": self.page.url})
        p.close()

    def _nav(self, frame):
        if frame is self.page.main_frame and frame.url.startswith("http") and origin(frame.url) != self.origin:
            self.events.append({"type": "offsite_navigation", "url": frame.url, "after_user_action": self._user()})

    def goto(self, url):
        self.last_action = time.time()
        for attempt in (0, 1):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                break
            except Exception:
                if attempt:          # a slow page is still usable if something rendered; otherwise give up
                    if not self.page.evaluate("() => !!(document.body && document.body.innerText.trim())"):
                        raise
        self.settle()

    def settle(self, ms=500):
        """Wait until the page stops changing: network quiet, then no DOM mutations for 600 ms (max ~4 s).
        Pages built in the browser (SPAs, carts loaded by script) are only readable once they settle."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        try:
            self.page.evaluate("""() => new Promise(done => { let t = setTimeout(fin, 600); const end = setTimeout(fin, 4000);
                const o = new MutationObserver(() => { clearTimeout(t); t = setTimeout(fin, 600); });
                function fin() { o.disconnect(); clearTimeout(end); done(); }
                o.observe(document.body || document.documentElement, {subtree: true, childList: true, characterData: true}); })""")
        except Exception:
            pass
        self.page.wait_for_timeout(ms)

    def snap(self) -> dict:
        for _ in range(3):
            try:
                s = self.page.evaluate(SNAPSHOT_JS)
                break
            except Exception:
                self.page.wait_for_timeout(700)
        else:
            s = {"url": self.page.url, "title": "", "text": "", "overlays": [], "elements": [], "payment_fields": False}
        s["by_id"] = {e["id"]: e for e in s["elements"]}
        return s

    def shot(self) -> str:
        return base64.b64encode(self.page.screenshot(type="jpeg", quality=55)).decode()

    def _loc(self, eid):
        return self.page.locator(f"[data-idt='{eid}']").first

    def act(self, a: dict, snap: dict) -> str:
        """Execute one action from a persona. Returns a short description. Raises on an unknown element."""
        eid, do = a.get("id"), a.get("do")
        el = snap["by_id"][eid]
        loc = self._loc(eid)
        self.last_action = time.time()
        if do == "click":
            self.last_click = (el.get("href") or "", el.get("name") or "")
            if not self.readonly and not el["region"].startswith("popup"):
                try:
                    self.autofilled = self.page.evaluate(AUTOFILL_JS, [eid, AUTOFILL])
                except Exception:
                    self.autofilled = []
            try:
                loc.scroll_into_view_if_needed(timeout=3000)
                loc.click(timeout=5000)
            except Exception:
                loc.evaluate("e => e.click()")
            self.settle()
            return f"click '{el['name']}'"
        if el["kind"] == "radio" and do in ("check", "select", "click"):
            if not el["checked"]:
                try:
                    loc.check(timeout=4000)
                except Exception:
                    loc.evaluate("e => e.click()")
            return f"choose '{el['name']}'" + (f" for '{el['question'][:60]}'" if el.get("question") else "")
        if do in ("check", "uncheck"):
            want = do == "check"
            if el["checked"] != want:
                try:
                    loc.click(timeout=4000)
                except Exception:
                    loc.evaluate("e => e.click()")
                self.page.wait_for_timeout(200)
            return f"{'tick' if want else 'untick'} '{el['name']}'"
        if do == "fill":
            val = str(a.get("value", ""))
            loc.fill(val, timeout=4000)
            return f"enter '{val}' in '{el['name'] or el['field']}'"
        if do == "select":
            val = str(a.get("value", ""))
            try:
                loc.select_option(label=val, timeout=4000)
            except Exception:
                loc.select_option(index=1 if len(el.get("options") or []) > 1 else 0, timeout=4000)
            return f"choose '{val}' in '{el['name']}'"
        raise ValueError(f"unknown action {do}")

    def close(self):
        try:
            self.ctx.close()
        except Exception:
            pass


def render(snap: dict, limit: int = 140) -> str:
    """Compact text view of the controls for an LLM prompt. Popups first, then main content, then navigation."""
    order = {"popup": 0, "main": 1, "nav": 2, "footer": 3}
    els = sorted(snap["elements"], key=lambda e: order.get(e["region"].split("#")[0], 1))[:limit]
    lines = []
    for e in els:
        flags = []
        if e["checked"] is not None:
            flags.append("TICKED" if e["checked"] else "unticked")
        if e["required"]:
            flags.append("required")
        if e["value"]:
            flags.append(f"value={e['value']!r}")
        if e["options"]:
            flags.append(f"options={e['options'][:6]}")
        if e["offsite"]:
            flags.append("→ other site")
        if e.get("question") and e["question"] != e["name"]:
            flags.append(f"question={e['question'][:120]!r}")
        if e["region"] != "main":
            flags.append(f"in {e['region']}")
        label = e["name"] or e["field"] or "(no label)"
        lines.append(f"{e['id']} {e['kind']} {label!r}" + (f" [{', '.join(flags)}]" if flags else ""))
    return "\n".join(lines)
