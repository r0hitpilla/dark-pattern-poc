"""Dark-pattern injection into real third-party websites, for an evaluation the engine's author did not build.

A test fixture, not part of the engine: `idt/` never imports it. It adds known dark patterns (or honest
look-alikes) to sites someone else wrote, inside our own browser only (Playwright init script). The live
sites are not changed. Ground truth comes from the injection, so it is known exactly.

Variants:  dark   = the patterns in SITES[site]["dark"]
           honest = look-alikes that are NOT dark patterns (fixed deadline, disclosed fee, labelled ads, optional
                    newsletter, neutral decline, plain consent, dismissal that sticks)
           clean  = no injection (the site as it is)

Not injectable from the browser side: interface interference via outcome, subscription trap and SaaS billing
(they need the site's server to behave differently). Those are covered by the local test shops.
"""
import json

SITES = {
    "sauce-demo": {
        "url": "https://sauce-demo.myshopify.com/",
        "cur": "£",
        "sel": {
            "add": "input.add-to-cart, button[name=add]",
            "listing_card": "section.product-grid > div",
            "listing_price": "h4",
            "cart_detect": "form[action='/cart']",
            "cart_rows": "form[action='/cart'] .actions",
            "cart_row_html": '<div class="row" data-inj-row="1"><div class="nine columns description"><div class="info"><h3>{label}</h3></div></div>'
                             '<div class="two columns price desktop">{amount}</div><div class="two columns quantity desktop"></div>'
                             '<div class="two columns total desktop">{amount}</div></div>',
            "cart_total": ".cart.total h2",
            "cart_total_fmt": "Total {amount}",
            "cart_line_total": "form[action='/cart'] .row .columns.total.desktop",
            "checkout": "form[action='/cart'] input[type=submit][value='Check Out']",
        },
        "dark": ["false_urgency", "false_scarcity", "basket_sneaking", "drip_pricing", "confirm_shaming", "nagging",
                 "disguised_ads", "rogue_malware", "trick_question", "bait_and_switch", "forced_action"],
    },
    "practicesoftwaretesting": {
        "url": "https://practicesoftwaretesting.com/",
        "cur": "$",
        "sel": {
            "add": "[data-test=add-to-cart]",
            "listing_card": "a.card",
            "listing_price": "[data-test=product-price]",
            "cart_detect": "[data-test=proceed-1]",
            "cart_rows": "table.table tbody",
            "cart_row_html": '<tr data-inj-row="1"><td>{label}</td><td></td><td class="text-end">{amount}</td><td class="text-end">{amount}</td><td></td></tr>',
            "cart_total": "[data-test=cart-total]",
            "cart_line_total": "[data-test=line-price]",
            "checkout": "[data-test=proceed-1]",
        },
        "dark": ["false_urgency", "false_scarcity", "basket_sneaking", "drip_pricing", "confirm_shaming", "nagging",
                 "disguised_ads", "rogue_malware", "trick_question", "bait_and_switch", "forced_action"],
    },
}

PAYLOAD = r"""
(() => {
  if (window.top !== window) return;
  const C = __CFG__, S = C.sel, V = C.variant, on = k => C.patterns.includes(k), dark = V === 'dark';
  const cur = C.cur, money = x => cur + x.toFixed(2);
  const parse = t => { const m = (t || '').replace(/,/g, '').match(/(\d+(?:\.\d+)?)/); return m ? parseFloat(m[1]) : null; };
  const add = (html, where, pos) => { const d = document.createElement('div'); d.innerHTML = html; const n = d.firstElementChild;
    where.insertAdjacentElement(pos || 'beforebegin', n); return n; };
  const FEE = 3.99, PROT = 2.49;
  // themes often keep hidden duplicates (mobile/desktop): always act on the visible element
  const qs = s => [...document.querySelectorAll(s)].find(e => e.offsetParent !== null) || null;
  const qsa = s => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null);
  function product() {
    const btn = qs(S.add); if (!btn || document.querySelector('[data-inj=urg]')) return;
    if (on('false_urgency')) {
      const end = dark ? Date.now() + 15 * 60e3 : Date.UTC(2026, 11, 31, 18, 0, 0);
      const el = add('<p data-inj="urg" style="color:#c00;font-weight:700">Deal ends in <span>--:--</span></p>', btn);
      const tick = () => { let s = Math.max(0, Math.floor((end - Date.now()) / 1000)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
        el.querySelector('span').textContent = (h ? h + ':' : '') + String(m).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };
      tick(); setInterval(tick, 1000);
    }
    if (on('false_scarcity') && dark) add('<p data-inj="stock" style="color:#c00;font-weight:700">Hurry! Only 2 left in stock</p>', btn);
    if (on('drip_pricing') && !dark) add(`<p data-inj="feeinfo">+ ${money(FEE)} service fee on every order</p>`, btn);
    if (on('rogue_malware') && dark) setTimeout(() => {
      add(`<div data-inj="mal" style="position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:99998;display:flex;align-items:center;justify-content:center">
        <div style="background:#fff3cd;border:2px solid #d39e00;padding:22px;width:400px;font-family:system-ui">
        <b>⚠ Your browser is out of date</b><p>Install the security update to keep shopping safely. Your download starts automatically.</p>
        <button onclick="this.closest('[data-inj=mal]').remove()">Later</button></div></div>`, document.body, 'beforeend');
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['MZ demo file, not software'], {type: 'application/octet-stream'}));
      a.download = 'BrowserUpdate.exe'; document.body.appendChild(a); a.click();
    }, 1200);
  }
  function listing() {
    const cards = [...document.querySelectorAll(S.listing_card)].filter(c => !c.hasAttribute('data-inj-card'));
    if (!cards.length) return;
    if (on('bait_and_switch') && dark) cards.forEach(c => { const p = c.querySelector(S.listing_price);
      if (p && !p.hasAttribute('data-inj-bait')) { const v = parse(p.textContent); if (v) { p.setAttribute('data-inj-bait', '1');
        p.textContent = money(Math.round(v * 0.7 * 100) / 100) + ' DEAL'; } } });
    if (on('disguised_ads') && !document.querySelector('[data-inj-card]')) {
      ['AeroBuds Pro Earbuds', 'TrailMax Rain Shell'].forEach((n, i) => { const c = cards[0].cloneNode(true); c.setAttribute('data-inj-card', '1');
        const href = `https://ads.adnetwork-demo.test/click?ad=${881 + i}&dest=partner`;
        (c.tagName === 'A' ? [c] : [...c.querySelectorAll('a')]).forEach(a => a.setAttribute('href', href));
        const t = c.querySelector('h3, h4, h5, [data-test=product-name], .card-title'); if (t) t.textContent = n;
        const p = c.querySelector(S.listing_price); if (p) p.textContent = money(39 + i * 10);
        c.querySelectorAll('img').forEach(im => im.setAttribute('alt', n));
        if (!dark) c.insertAdjacentHTML('afterbegin', '<span style="font-size:11px;border:1px solid #888;padding:1px 4px">Sponsored</span>');
        cards[0].insertAdjacentElement('beforebegin', c); });
    }
  }
  function cart() {
    if (!qs(S.cart_detect)) return;
    const rowsAt = qs(S.cart_rows); if (!rowsAt) return;
    const extras = [];
    if (on('basket_sneaking') && dark) extras.push(['Shipping protection', PROT]);
    if (on('drip_pricing')) extras.push(['Service fee', FEE]);
    if (!document.querySelector('[data-inj-row]')) {
      extras.forEach(([l, a]) => { const h = S.cart_row_html.replace('{label}', l).split('{amount}').join(money(a));
        rowsAt.tagName === 'TBODY' ? rowsAt.insertAdjacentHTML('beforeend', h) : rowsAt.insertAdjacentHTML('beforebegin', h); });
    }
    // grand total including the extras
    const lines = qsa(S.cart_line_total).filter(e => !e.closest('[data-inj-row]')).map(e => parse(e.textContent) || 0);
    const base = lines.reduce((x, y) => x + y, 0), sum = base + extras.reduce((x, [, a]) => x + a, 0);
    if (S.cart_total) { const t = qs(S.cart_total), want = (S.cart_total_fmt || '{amount}').replace('{amount}', money(sum));
      if (t && extras.length && t.textContent.trim() !== want) t.textContent = want; }
    else if (extras.length) { let t = document.querySelector('[data-inj=total]');
      if (!t) t = add('<p data-inj="total" style="font-size:18px"><b>Order total: <span></span></b></p>', rowsAt);
      t.querySelector('span').textContent = money(sum); }
    const chk = qs(S.checkout);
    if (!chk || document.querySelector('[data-inj=cartbox]')) return;
    let box = '<div data-inj="cartbox" style="margin:14px 0;padding:12px;border:1px solid #ddd">';
    if (on('basket_sneaking') && !dark) box += `<p><button type="button" onclick="this.textContent='Added'">Add shipping protection for ${money(PROT)}</button></p>`;
    if (on('confirm_shaming')) box += `<p><b>Protect your order with VIP Care for ${money(4.99)}</b></p>
      <p><button type="button" style="background:#e85d00;color:#fff;font-size:20px;padding:12px 30px;border:0"
        onclick="this.closest('p').innerHTML='VIP Care added'">Yes, add VIP Care</button>
      ${dark ? `<a href="#" onclick="this.closest('p').remove();return false" style="font-size:11px;color:#999;margin-left:8px">No thanks, I don't care about my stuff</a>`
             : `<button type="button" onclick="this.closest('p').remove()" style="background:#e85d00;color:#fff;font-size:20px;padding:12px 30px;border:0;margin-left:8px">No thanks</button>`}</p>`;
    if (on('trick_question')) box += dark
      ? '<label style="display:block"><input type="checkbox" checked data-inj="tq"> Uncheck this box if you do not want to not receive offers from our partners</label>'
      : '<label style="display:block"><input type="checkbox" data-inj="tq"> Send me offers from our partners</label>';
    if (on('forced_action')) box += dark
      ? '<label style="display:block"><input type="checkbox" data-inj="nl"> Subscribe me to the newsletter</label><p data-inj="err" style="color:#c00"></p>'
      : '<label style="display:block"><input type="checkbox" data-inj="nl"> Subscribe me to the newsletter (optional)</label>';
    box += '</div>';
    add(box, chk.closest('div, form, td') || chk);
    if (on('forced_action') && dark) document.addEventListener('click', ev => {
      const hit = ev.target.closest(S.checkout); if (!hit || hit.offsetParent === null) return; const nl = document.querySelector('[data-inj=nl]');
      if (nl && !nl.checked) { ev.preventDefault(); ev.stopImmediatePropagation();
        document.querySelector('[data-inj=err]').textContent = 'You must subscribe to our newsletter to check out.'; } }, true);
  }
  function nag() {
    if (!on('nagging') || document.querySelector('[data-inj=nag]')) return;
    try { if (!dark && localStorage.getItem('inj_nag_closed')) return; } catch (e) {}
    if (window.__injNagShown) return; window.__injNagShown = true;
    add(`<div data-inj="nag" style="position:fixed;right:20px;bottom:20px;width:300px;background:#fff;border:2px solid #333;padding:16px;z-index:99997;font-family:system-ui">
      <b>Get 10% off your next order</b><p>Join our mailing list for exclusive deals.</p>
      <button type="button" aria-label="Close" onclick="try{localStorage.setItem('inj_nag_closed','1')}catch(e){};this.closest('[data-inj=nag]').remove()">Close</button></div>`,
      document.body, 'beforeend');
  }
  let last = '';
  const run = () => { if (!document.body) return; try { product(); listing(); cart(); } catch (e) {}
    if (location.href !== last) { last = location.href; window.__injNagShown = false; setTimeout(() => { try { nag(); } catch (e) {} }, 800); } };
  document.addEventListener('DOMContentLoaded', run);
  setInterval(run, 400);
})();
"""


def hook(site: str, variant: str):
    """A context hook for idt.perceive.CONTEXT_HOOKS, or None for the clean variant."""
    if variant == "clean":
        return None
    cfg = SITES[site]
    js = PAYLOAD.replace("__CFG__", json.dumps({"sel": cfg["sel"], "cur": cfg["cur"], "variant": variant,
                                                "patterns": cfg["dark"]}))
    return lambda ctx: ctx.add_init_script(script=js)


def truth(site: str, variant: str) -> list:
    return list(SITES[site]["dark"]) if variant == "dark" else []
