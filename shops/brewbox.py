"""
Brewbox: a fictional coffee shop with a subscription club. Second test target for the generic engine.

Deliberately unlike Kartiq: US dollars, no <main>/<header>/<nav> landmarks, no tables (div rows), a custom popup
without role=dialog, a cookie banner, account-based checkout and a card form at the payment step.

dark  : seeds the patterns in SEEDED below.
clean : honest control: equal cookie choices, guest checkout, shipping shown up front, trial terms stated before
        signing up, online cancellation, a newsletter popup that stays closed.
Nothing here takes payment.
"""
from flask import Flask, session, request, redirect, render_template_string, jsonify, make_response

SEEDED = {
    "interface_interference": "Cookie banner: 'Accept all' on the first layer, refusing needs a settings page with pre-ticked toggles",
    "forced_action": "Checkout requires creating an account and joining the newsletter; no guest checkout",
    "drip_pricing": "'Free shipping' on the product page; service and small-order fees appear only at payment",
    "saas_billing": "Club trial page never states the price; '$24.99/month' appears only on the account page after joining",
    "subscription_trap": "Club can only be cancelled by phone",
    "nagging": "Newsletter popup comes back on every page after being closed",
}
COFFEES = {"yirgacheffe": ("Ethiopia Yirgacheffe", 18.00), "huila": ("Colombia Huila", 16.00), "espresso": ("House Espresso", 14.00)}
CLUB = 24.99

BASE = """<!doctype html><html><head><meta charset="utf-8"><title>{{ title }} | Brewbox</title><style>
body{margin:0;font-family:Georgia,serif;background:#fbf7f2;color:#2b2118}
.top{display:flex;gap:18px;align-items:center;padding:14px 28px;background:#2b2118;color:#f5e9dc}
.top a{color:#f5e9dc;text-decoration:none}.logo{font-weight:700;font-size:22px;margin-right:auto}
.wrap{max-width:820px;margin:28px auto;padding:0 20px}
.cards{display:flex;gap:16px;flex-wrap:wrap}.card{background:#fff;border:1px solid #e8dccd;border-radius:10px;padding:16px;width:230px}
.amt{font-weight:700}.small{font-size:12px;color:#8a7a6a}
.go{background:#c0612b;color:#fff;border:0;border-radius:24px;padding:12px 26px;font-size:16px;cursor:pointer;text-decoration:none;display:inline-block}
.ghost{background:none;border:1px solid #2b2118;border-radius:24px;padding:10px 20px;font-size:14px;cursor:pointer;color:#2b2118;text-decoration:none;display:inline-block}
.row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #eadfd2}
.f{display:block;margin:10px 0}.f input,.f select{display:block;padding:8px;width:280px}
.err{color:#b00020;font-weight:700}
.cookie{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:2px solid #2b2118;padding:16px 28px;display:flex;gap:14px;align-items:center}
.pop{position:fixed;inset:0;background:rgba(43,33,24,.55);display:flex;align-items:center;justify-content:center}
.pop .box{background:#fff;padding:26px;border-radius:12px;width:340px;position:relative}
.x{position:absolute;right:10px;top:6px;border:0;background:none;font-size:22px;cursor:pointer}
</style></head><body>
<div class="top"><span class="logo">Brewbox</span><a href="/">Coffee</a><a href="/club">Club</a><a href="/bag">Bag ({{ n }})</a><a href="/me">My account</a></div>
<div class="wrap">{{ body|safe }}</div>
{% if pop %}<div class="pop" id="nl"><div class="box">
<button class="x" aria-label="Close" type="button" onclick="fetch('/nl/close',{method:'POST'});document.getElementById('nl').remove()">×</button><h3>Get 10% off your first bag</h3><p>Join 40,000 coffee lovers.</p>
<form method="post" action="/nl/close"><input type="hidden" name="back" value="{{ path }}"><input name="nl_email" placeholder="Email address">
<button class="go" type="submit">Get my 10% off</button></form></div></div>{% endif %}
{% if cookie %}<div class="cookie"><span>We use cookies to improve your experience and for marketing.</span>
<form method="post" action="/consent"><input type="hidden" name="back" value="{{ path }}"><button class="go" name="c" value="all" type="submit">Accept all</button>
{% if not dark %}<button class="go" name="c" value="none" type="submit">Reject all</button>{% endif %}</form>
<a class="small" href="/privacy-settings?back={{ path }}">Customize</a></div>{% endif %}
</body></html>"""


def create_app(mode="dark"):
    dark = mode == "dark"
    app = Flask(f"brewbox_{mode}")
    app.secret_key = f"brewbox-{mode}"
    app.config["SESSION_COOKIE_NAME"] = f"brewbox_{mode}"

    def page(title, body):
        s = session
        s.setdefault("bag", [])
        hide = s.pop("nl_hide_once", False)
        pop = not hide and (dark or not s.get("nl_closed")) and request.path not in ("/privacy-settings",)
        if not s.get("nl_seen"):
            s["nl_seen"] = True
        cookie = request.cookies.get(f"bb_consent_{mode}") is None and request.path != "/privacy-settings"
        return render_template_string(BASE, title=title, body=body, n=sum(q for _, q, _ in s["bag"]), pop=pop,
                                      cookie=cookie, dark=dark, path=request.path)

    def money(x):
        return f"${x:,.2f}"

    @app.post("/nl/close")
    def nl_close():
        session["nl_closed"] = True
        if request.form.get("back"):          # the email form; the × button closes in place without a reload
            session["nl_hide_once"] = True
            return redirect(request.form["back"])
        return ("", 204)

    @app.post("/consent")
    def consent():
        r = make_response(redirect(request.form.get("back") or "/"))
        r.set_cookie(f"bb_consent_{mode}", request.form.get("c", "custom"))
        return r

    @app.route("/privacy-settings", methods=["GET", "POST"])
    def privacy():
        back = request.values.get("back", "/")
        if request.method == "POST":
            chosen = [k for k in ("analytics", "marketing", "personalisation") if request.form.get(k)]
            r = make_response(redirect(back))
            r.set_cookie(f"bb_consent_{mode}", ",".join(chosen) or "necessary")
            return r
        on = "checked" if dark else ""
        boxes = "".join(f'<label class="f"><input type="checkbox" name="{k}" value="1" {on}> {k.title()} cookies</label>'
                        for k in ("analytics", "marketing", "personalisation"))
        return page("Privacy settings", f"""<h1>Privacy settings</h1><form method="post"><input type="hidden" name="back" value="{back}">
            <label class="f"><input type="checkbox" checked disabled> Strictly necessary (always on)</label>{boxes}
            <button class="ghost" type="submit">Save choices</button></form>""")

    @app.get("/")
    def home():
        cards = "".join(f'<div class="card"><a href="/coffee/{k}"><b>{n}</b></a><p class="amt">{money(p)}</p><p class="small">250 g bag</p></div>'
                        for k, (n, p) in COFFEES.items())
        return page("Fresh coffee", f"<h1>Fresh-roasted coffee</h1><div class='cards'>{cards}</div>")

    @app.get("/coffee/<k>")
    def coffee(k):
        n, p = COFFEES[k]
        ship = "<p>Free shipping on every order</p>" if dark else "<p>+ $5.00 shipping</p>"
        return page(n, f"""<h1>{n}</h1><p class="amt" style="font-size:28px">{money(p)}</p>{ship}
          <form method="post" action="/bag/add"><input type="hidden" name="k" value="{k}">
          <label class="f">Grind <select name="grind" required><option value="">Choose…</option><option>Whole bean</option><option>Filter</option><option>Espresso</option></select></label>
          <button class="go" type="submit">Add to bag</button></form>""")

    @app.post("/bag/add")
    def bag_add():
        session.setdefault("bag", [])
        session["bag"] = session["bag"] + [[request.form["k"], 1, request.form.get("grind") or "Whole bean"]]
        return redirect("/bag")

    def lines():
        rows, sub = "", 0.0
        for k, q, g in session.get("bag", []):
            n, p = COFFEES[k]
            sub += p * q
            rows += f'<div class="row"><span>{n} ({g}) × {q}</span><span>{money(p * q)}</span></div>'
        return rows, sub

    @app.get("/bag")
    def bag():
        rows, sub = lines()
        if not rows:
            return page("Bag", "<h1>Your bag is empty</h1>")
        return page("Bag", f"""<h1>Your bag</h1>{rows}<div class="row"><b>Subtotal</b><b>{money(sub)}</b></div>
            <p><a class="go" href="/checkout">Checkout</a></p>""")

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        err = ""
        if request.method == "POST":
            f = request.form
            if dark and not f.get("newsletter"):
                err = "You must join the Brewbox newsletter to place an order."
            elif dark and len(f.get("password", "")) < 6:
                err = "Please create a password to continue."
            else:
                session["user"] = f.get("email")
                return redirect("/checkout/pay")
        if dark:
            acct = """<p><b>Create your Brewbox account to continue.</b> Guest checkout is not available.</p>
              <label class="f">Email <input name="email" type="email" required></label>
              <label class="f">Password <input name="password" type="password" required></label>
              <label class="f"><input type="checkbox" name="newsletter" value="1"> Sign me up for the Brewbox newsletter</label>"""
        else:
            acct = """<label class="f">Email <input name="email" type="email" required></label>
              <label class="f"><input type="checkbox" name="newsletter" value="1"> Send me the Brewbox newsletter (optional)</label>"""
        return page("Checkout", f"""<h1>Checkout</h1>{f'<p class="err">{err}</p>' if err else ''}<form method="post">{acct}
            <label class="f">Full name <input name="name" required></label><label class="f">Street address <input name="addr" required></label>
            <label class="f">ZIP code <input name="zip" required></label>
            <button class="go" type="submit">Continue to payment</button></form>""")

    @app.get("/checkout/pay")
    def pay():
        rows, sub = lines()
        extra = [("Service fee", 2.99), ("Small-order fee", 1.50)] if dark else [("Shipping", 5.00)]
        tot = sub + sum(a for _, a in extra)
        rows += "".join(f'<div class="row"><span>{l}</span><span>{money(a)}</span></div>' for l, a in extra)
        return page("Payment", f"""<h1>Payment</h1>{rows}<div class="row"><b>Order total</b><b>{money(tot)}</b></div>
            <label class="f">Card number <input autocomplete="cc-number" name="cc"></label>
            <label class="f">Expiry <input autocomplete="cc-exp" name="exp"></label>
            <button class="go" type="button" onclick="alert('Demo shop: no payment is taken')">Pay {money(tot)}</button>""")

    @app.get("/club")
    def club():
        terms = ("<p>Fresh beans delivered every month. Try it free for 14 days.</p>" if dark else
                 f"<p>Fresh beans delivered every month. Free for 14 days, then {money(CLUB)}/month. Cancel anytime online.</p>")
        return page("Club", f"<h1>Brewbox Club</h1>{terms}<a class='go' href='/club/join'>Start free trial</a>")

    @app.route("/club/join", methods=["GET", "POST"])
    def club_join():
        if request.method == "POST":
            session["user"] = request.form.get("email")
            session["club"] = True
            return redirect("/me")
        terms = "" if dark else f"<p>Your trial is free for 14 days, then {money(CLUB)}/month until you cancel.</p>"
        return page("Join the Club", f"""<h1>Join Brewbox Club</h1>{terms}<form method="post">
            <label class="f">Email <input name="email" type="email" required></label>
            <label class="f">Password <input name="password" type="password" required></label>
            <button class="go" type="submit">Start my free trial</button></form>""")

    @app.get("/me")
    def me():
        if not session.get("user"):
            return page("My account", "<h1>My account</h1><p>You are not signed in. <a href='/club'>Join the Club</a> or check out to create an account.</p>")
        plan = (f"Brewbox Club (free trial) — renews at {money(CLUB)}/month on 23 Oct 2026" if session.get("club") else "No plan")
        manage = "<p><a class='ghost' href='/me/plan'>Manage plan</a></p>" if session.get("club") else ""
        return page("My account", f"""<h1>My account</h1><div class="row"><span>Signed in as</span><span>{session['user']}</span></div>
            <div class="row"><span>Plan</span><span id="plan">{plan}</span></div>{manage}""")

    @app.route("/me/plan", methods=["GET", "POST"])
    def plan():
        if dark:
            return page("Manage plan", """<h1>Manage your plan</h1><p>We'd hate to see you go! To cancel your Club membership,
                please call our team on 1-800-555-0199 (Mon–Fri, 9am–5pm ET).</p><a class="go" href="/me">Back to my account</a>""")
        if request.method == "POST":
            if request.form.get("sure"):
                session["club"] = False
                return redirect("/me")
            return page("Cancel", """<h1>Cancel Brewbox Club?</h1><form method="post"><input type="hidden" name="sure" value="1">
                <button class="go" type="submit">Yes, cancel my membership</button></form>""")
        return page("Manage plan", """<h1>Manage your plan</h1><form method="post"><button class="ghost" type="submit">Cancel membership</button></form>""")

    @app.get("/__ground_truth")
    def gt():
        return jsonify({"mode": mode, "seeded": list(SEEDED) if dark else []})

    return app
