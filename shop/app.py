"""
Kartiq — a fictional demo shop used as the test target for the Intent-Divergence harness.

It runs in two modes from the same code:

  dark  : seeds 8 CCPA (India) dark patterns, listed in SEEDED_PATTERNS below.
  clean : an honest control. It still shows urgency and scarcity, but they are TRUE
          (an absolute sale deadline, a stock count that matches inventory), fees are
          disclosed up front, Plus is offered neutrally and cancelling is easy.

The clean shop is what makes the demo honest: a recognition-based detector that
flags "urgency language" will flag both shops, while a behavioural test should
flag only the dark one.

Nothing here takes payment. The final step shows a "Pay" button that does nothing,
and the harness is built never to press it.
"""
import time
from flask import Flask, session, request, redirect, url_for, render_template_string, jsonify, make_response

SEEDED_PATTERNS = {
    "false_urgency": "Product-page countdown restarts at 15:00 for every visitor/page load",
    "false_scarcity": "'Only 2 left' shown while inventory holds 140 units",
    "basket_sneaking": "Paid 'Kartiq Protect' add-on is pre-ticked on the product page",
    "drip_pricing": "Convenience and handling fees appear only on the final review step",
    "interface_interference": "Plus trial is the dominant checkout button; plain checkout is a small grey link",
    "confirm_shaming": "Decline link reads 'No thanks, I hate saving money'",
    "trick_question": "Pre-ticked partner-offers consent worded with a double negative",
    "subscription_trap": "Joining Plus takes 2 clicks; cancelling takes 6 with a survey and retention offer",
    "nagging": "'Get the app' dialog reappears on every page even after it is dismissed",
}

APP_START = time.time()

PRODUCTS = {
    "tee": {"name": "Classic Black Tee", "price": 499},
    "cap": {"name": "Canvas Cap", "price": 349},
    "bottle": {"name": "Steel Bottle", "price": 599},
}
PROTECT_PRICE = 49
PLUS_PRICE = 199


BASE = """<!doctype html><html><head><meta charset="utf-8"><title>{{ title }} · Kartiq</title>
<style>
 body{font-family:system-ui,sans-serif;margin:0;background:#f6f6f4;color:#222}
 header{background:#1d3557;color:#fff;padding:12px 24px;display:flex;gap:24px;align-items:center}
 header a{color:#fff;text-decoration:none} header .brand{font-weight:700;font-size:20px;margin-right:auto}
 main{max-width:860px;margin:24px auto;background:#fff;padding:24px 32px;border-radius:8px}
 .price{font-size:32px;font-weight:700} .muted{color:#888;font-size:12px}
 .btn{display:inline-block;padding:10px 18px;border-radius:6px;border:1px solid #1d3557;background:#fff;color:#1d3557;font-size:15px;cursor:pointer;text-decoration:none}
 .btn-primary{background:#1d3557;color:#fff}
 .btn-huge{background:#ff7a00;color:#fff;border:none;font-size:22px;padding:18px 40px;font-weight:700;width:100%}
 .tiny-link{color:#aaa;font-size:11px}
 .urgency{color:#c1121f;font-weight:600}
 table{border-collapse:collapse;width:100%} td{padding:6px 4px;border-bottom:1px solid #eee}
 td.amt{text-align:right}
 .overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center}
 .dialog{background:#fff;padding:24px;border-radius:8px;width:320px;text-align:center}
 label{display:block;margin:10px 0}
</style></head><body>
<header><span class="brand">Kartiq</span><a href="/">Home</a><a href="/plus">Plus</a><a href="/account">Account</a><a href="/cart">Cart ({{ cart_count }})</a></header>
<main>{{ body|safe }}</main>
{% if show_nag %}
<div class="overlay" id="nag" role="dialog" aria-label="Get the app">
  <div class="dialog"><h3>Shopping is better on the app!</h3><p>Get the Kartiq app for app-only deals.</p>
  <a class="btn btn-primary" href="#">Install app</a>
  <form method="post" action="/nag/dismiss" style="display:inline"><input type="hidden" name="next" value="{{ request.path }}">
  <button class="btn" type="submit">Not now</button></form></div>
</div>
{% endif %}
<script>
document.querySelectorAll('[data-deadline]').forEach(function(el){
  var d=parseInt(el.dataset.deadline,10);
  function tick(){var s=Math.max(0,Math.floor((d-Date.now())/1000));
    var h=Math.floor(s/3600),m=Math.floor((s%3600)/60),x=s%60;
    el.textContent=(h>0?h+':':'')+String(m).padStart(2,'0')+':'+String(x).padStart(2,'0');}
  tick(); setInterval(tick,1000);
});
</script>
</body></html>"""


def create_app(mode: str = "dark") -> Flask:
    assert mode in ("dark", "clean")
    dark = mode == "dark"
    app = Flask(f"kartiq_{mode}")
    app.secret_key = f"kartiq-demo-{mode}"
    app.config["SESSION_COOKIE_NAME"] = f"kartiq_{mode}"
    inventory = {"tee": 140 if dark else 3, "cap": 60, "bottle": 25}

    def state():
        s = session
        s.setdefault("cart", [])          # list of {"sku", "qty"}
        s.setdefault("protect", False)
        s.setdefault("plus", "none")      # none | trial
        s.setdefault("partner_offers", False)
        s.setdefault("nag_dismissed", False)
        return s

    def page(title, body, **kw):
        s = state()
        if s.pop("nag_hide_next", False):          # the page you land on right after "Not now"
            session.modified = True
            show_nag = False
        else:
            show_nag = dark or not s["nag_dismissed"]  # dark: forgets the dismissal on the next page
        count = sum(i["qty"] for i in s["cart"])
        return render_template_string(BASE, title=title, body=body, cart_count=count,
                                      show_nag=show_nag, request=request, **kw)

    @app.post("/nag/dismiss")
    def nag_dismiss():
        s = state()
        s["nag_dismissed"] = True
        s["nag_hide_next"] = True
        session.modified = True
        return redirect(request.form.get("next") or "/")

    @app.get("/")
    def home():
        items = "".join(
            f'<li><a href="/product/{k}">{p["name"]}</a> — ₹{p["price"]}</li>' for k, p in PRODUCTS.items())
        return page("Home", f"<h1>Today's picks</h1><ul>{items}</ul>")

    @app.get("/product/<sku>")
    def product(sku):
        p = PRODUCTS[sku]
        if dark:
            deadline = time.time() + 15 * 60          # restarts for everyone, every load
            stock_line = '<p class="urgency">Hurry! Only 2 left in stock</p>'
            price_line = f'<div class="price">₹{p["price"]}</div><p>FREE delivery</p>'
            addon = (f'<label class="muted"><input type="checkbox" name="protect" value="1" checked> '
                     f'Add Kartiq Protect accidental-damage cover for ₹{PROTECT_PRICE}</label>')
        else:
            deadline = APP_START + 2 * 3600            # one real sale deadline for everyone
            n = inventory[sku]
            stock_line = (f'<p class="urgency">Only {n} left in stock</p>' if n <= 5
                          else f'<p>{n} in stock</p>')
            price_line = f'<div class="price">₹{p["price"]}</div><p>+ ₹40 delivery</p>'
            addon = (f'<label><input type="checkbox" name="protect" value="1"> '
                     f'Add Kartiq Protect accidental-damage cover for ₹{PROTECT_PRICE}</label>')
        body = f"""<h1>{p['name']}</h1>{price_line}
        <p class="urgency">Deal ends in <span class="timer" data-deadline="{int(deadline*1000)}">--:--</span></p>
        {stock_line}
        <form method="post" action="/cart/add">
          <input type="hidden" name="sku" value="{sku}">
          <label>Quantity <input type="number" name="qty" value="1" min="1" max="5"></label>
          {addon}
          <button class="btn btn-primary" style="font-size:20px;padding:14px 32px" type="submit">Add to cart</button>
        </form>"""
        return page(p["name"], body)

    @app.get("/api/inventory/<sku>")
    def inv(sku):
        """System-of-record endpoint, as a client would expose in UAT for the audit."""
        return jsonify({"sku": sku, "units_available": inventory[sku]})

    @app.post("/cart/add")
    def cart_add():
        s = state()
        sku = request.form["sku"]
        qty = int(request.form.get("qty", 1))
        cart = s["cart"]
        for line in cart:
            if line["sku"] == sku:
                line["qty"] += qty
                break
        else:
            cart.append({"sku": sku, "qty": qty})
        if request.form.get("protect"):
            s["protect"] = True
        session.modified = True
        return redirect("/cart")

    def cart_rows(s):
        rows, sub = "", 0
        for line in s["cart"]:
            p = PRODUCTS[line["sku"]]
            amt = p["price"] * line["qty"]
            sub += amt
            rows += f'<tr><td>{p["name"]} × {line["qty"]}</td><td class="amt">₹{amt}</td></tr>'
        return rows, sub

    @app.get("/cart")
    def cart():
        s = state()
        if not s["cart"]:
            return page("Cart", "<h1>Your cart is empty</h1>")
        rows, sub = cart_rows(s)
        if dark:
            actions = """
            <form method="post" action="/cart/checkout"><input type="hidden" name="plus" value="1">
              <button class="btn-huge" type="submit">Checkout with Kartiq Plus — FREE 30-day trial</button></form>
            <p style="text-align:center"><a class="tiny-link" href="/checkout">No thanks, I hate saving money</a></p>"""
        else:
            actions = """
            <p><a class="btn btn-primary" style="font-size:18px;padding:12px 28px" href="/checkout">Proceed to checkout</a></p>
            <p><a href="/plus">Learn about Kartiq Plus (₹199/month)</a></p>"""
        return page("Cart", f"<h1>Your cart</h1><table>{rows}<tr><td><b>Subtotal</b></td>"
                            f"<td class='amt'><b>₹{sub}</b></td></tr></table>{actions}")

    @app.post("/cart/checkout")
    def cart_checkout_plus():
        s = state()
        if request.form.get("plus"):
            s["plus"] = "trial"
            session.modified = True
        return redirect("/checkout")

    @app.get("/checkout")
    def checkout():
        if dark:
            consent = ('<label><input type="checkbox" name="partner_offers" value="1" checked> '
                       'Do not tick this box if you do not want to receive offers from our partners</label>')
        else:
            consent = ('<label><input type="checkbox" name="partner_offers" value="1"> '
                       'Send me offers from Kartiq partners</label>')
        body = f"""<h1>Delivery details</h1>
        <form method="post" action="/checkout">
          <label>Name <input name="name" value="Test User" required></label>
          <label>Address <input name="address" value="12 MG Road, Bengaluru 560001" required></label>
          {consent}
          <button class="btn btn-primary" style="font-size:20px;padding:14px 32px" type="submit">Continue to review</button>
        </form>"""
        return page("Checkout", body)

    @app.post("/checkout")
    def checkout_post():
        s = state()
        s["partner_offers"] = bool(request.form.get("partner_offers"))
        session.modified = True
        return redirect("/checkout/review")

    @app.get("/checkout/review")
    def review():
        s = state()
        rows, total = cart_rows(s)
        extra = []
        if s["protect"]:
            extra.append(("Kartiq Protect", PROTECT_PRICE))
        if dark:
            extra += [("Convenience fee", 29), ("Handling charges", 19)]
        else:
            extra.append(("Delivery", 40))
        for label, amt in extra:
            rows += f'<tr><td>{label}</td><td class="amt">₹{amt}</td></tr>'
            total += amt
        plus_note = ""
        if s["plus"] == "trial":
            plus_note = f'<p class="muted">Kartiq Plus trial active. ₹{PLUS_PRICE}/month after 30 days.</p>'
        body = f"""<h1>Review your order</h1><table>{rows}
          <tr><td><b>Total payable</b></td><td class="amt"><b>₹{total}</b></td></tr></table>{plus_note}
          <p><button class="btn btn-primary" id="pay" type="button" onclick="alert('Demo shop: no payment is taken')">Pay ₹{total}</button></p>"""
        return page("Review", body)

    # ---------------- account / membership ----------------
    @app.get("/account")
    def account():
        s = state()
        member = s["plus"] != "none"
        status = "Kartiq Plus (trial)" if member else "Not a member"
        offers = "On" if s["partner_offers"] else "Off"
        if member:
            link = ('<a class="btn" href="/plus/manage">Manage membership</a>' if dark
                    else '<form method="post" action="/plus/cancel"><button class="btn" type="submit">Cancel membership</button></form>')
        else:
            link = '<a class="btn btn-primary" href="/plus">Join Kartiq Plus</a>'
        body = f"""<h1>Your account</h1>
        <table><tr><td>Membership</td><td id="membership">{status}</td></tr>
        <tr><td>Partner offers &amp; data sharing</td><td id="partner-offers">{offers}</td></tr></table>
        <p>{link}</p>"""
        return page("Account", body)

    @app.get("/plus")
    def plus():
        return page("Plus", f"""<h1>Kartiq Plus</h1><p>Free delivery and early sales. ₹{PLUS_PRICE}/month after a 30-day free trial.</p>
        <form method="post" action="/plus/join"><button class="btn btn-primary" type="submit">Start membership</button></form>""")

    @app.post("/plus/join")
    def plus_join():
        state()["plus"] = "trial"
        session.modified = True
        return redirect("/account")

    # dark: long cancellation path
    @app.get("/plus/manage")
    def plus_manage():
        return page("Manage", """<h1>Manage membership</h1><p>You're saving with Plus!</p>
        <a class="btn btn-primary" href="/account">Back to account</a>
        <p><a class="tiny-link" href="/plus/cancel/reason">Cancel membership</a></p>""")

    @app.get("/plus/cancel/reason")
    def plus_reason():
        return page("Cancel", """<h1>Why are you leaving?</h1>
        <form method="post" action="/plus/cancel/reason">
          <label><input type="radio" name="reason" value="price" required> Too expensive</label>
          <label><input type="radio" name="reason" value="usage"> I don't use it enough</label>
          <label><input type="radio" name="reason" value="other"> Other</label>
          <button class="btn" type="submit">Next</button></form>""")

    @app.post("/plus/cancel/reason")
    def plus_reason_post():
        return redirect("/plus/cancel/offer")

    @app.get("/plus/cancel/offer")
    def plus_offer():
        return page("Wait!", """<h1>Wait! Get 3 months at 50% off</h1>
        <form method="post" action="/plus/keep"><button class="btn-huge" type="submit">Keep my benefits</button></form>
        <p style="text-align:center"><a class="tiny-link" href="/plus/cancel/confirm">Continue cancelling</a></p>""")

    @app.post("/plus/keep")
    def plus_keep():
        return redirect("/account")

    @app.get("/plus/cancel/confirm")
    def plus_confirm():
        return page("Confirm", """<h1>Are you sure?</h1><p>You'll lose free delivery and early sales.</p>
        <form method="post" action="/plus/cancel"><button class="btn" type="submit">Confirm cancellation</button></form>""")

    @app.post("/plus/cancel")
    def plus_cancel():
        if not dark and not request.form.get("confirmed"):
            # clean: one confirmation screen, then done
            return page("Confirm", """<h1>Cancel Kartiq Plus?</h1>
            <form method="post" action="/plus/cancel"><input type="hidden" name="confirmed" value="1">
            <button class="btn btn-primary" type="submit">Confirm cancellation</button></form>""")
        state()["plus"] = "none"
        session.modified = True
        return redirect("/account")

    @app.get("/__ground_truth")
    def ground_truth():
        """Seeded patterns, for scoring only. The harness never reads this while testing."""
        return jsonify({"mode": mode, "seeded": list(SEEDED_PATTERNS) if dark else []})

    return app


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["dark", "clean"], default="dark")
    ap.add_argument("--port", type=int, default=5001)
    a = ap.parse_args()
    create_app(a.mode).run(port=a.port)
