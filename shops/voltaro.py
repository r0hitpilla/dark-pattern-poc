"""
Voltaro: a fictional electronics shop. Third test target for the generic engine.

Deliberately unlike Kartiq and Brewbox: euro prices written '49,00 €', a search/results grid with sponsored
placements, a basket that changes itself, a radio-button consent question, and no account or membership.

dark  : seeds the patterns in SEEDED below.
clean : honest control: ads labelled 'Sponsored', the listed price is the product price, stock claims are
        enforced by the basket, protection is an optional button, plain consent checkbox, no downloads.
Nothing here takes payment.
"""
from flask import Flask, session, request, redirect, render_template_string, jsonify, send_file
import io

SEEDED = {
    "bait_and_switch": "Results list the X5 headphones at 49,00 € ('Flash deal'); the product page charges 79,00 €",
    "disguised_ads": "Two advertiser links sit at the top of the results styled as products, with no 'Sponsored' label",
    "rogue_malware": "Product page imitates a browser warning and starts downloading VoltaroHelper.exe by itself",
    "false_scarcity": "'Only 1 left in stock!' while the basket accepts any quantity",
    "basket_sneaking": "Adding headphones silently adds a 12,99 € protection plan to the basket",
    "trick_question": "Consent asked as 'Would you prefer not to opt out of personalised partner marketing?', pre-set to Yes",
}
ITEMS = {"x5": ("Voltaro X5 Wireless Headphones", 79.0, 49.0), "p2": ("Pulse P2 Bluetooth Speaker", 39.0, 39.0),
         "c9": ("ChargeCube 65W USB-C Charger", 29.0, 29.0), "k1": ("Kestrel K1 Mechanical Keyboard", 89.0, 89.0)}
PLAN = 12.99


def eur(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


BASE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{{ title }} – Voltaro</title><style>
body{margin:0;font-family:Helvetica,Arial,sans-serif;background:#eef1f5;color:#111}
header{background:#0b3d91;color:#fff;padding:12px 24px;display:flex;gap:16px;align-items:center}
header a{color:#fff}.brand{font-size:20px;font-weight:800;margin-right:12px}
header form{display:flex;gap:6px;flex:1}header input{flex:1;padding:8px}
main{max-width:960px;margin:20px auto;background:#fff;padding:20px 26px;border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.tile{border:1px solid #d9dee6;padding:12px;border-radius:4px}
.tile h3{font-size:15px;margin:6px 0}.p{font-size:20px;font-weight:700;color:#0b3d91}.deal{background:#ffd400;padding:2px 6px;font-size:11px;font-weight:700}
.spon{font-size:11px;color:#666;border:1px solid #999;padding:1px 4px}
.cta{background:#ff6a00;color:#fff;border:0;padding:12px 22px;font-size:16px;font-weight:700;cursor:pointer;border-radius:3px;text-decoration:none;display:inline-block}
.sec{background:#fff;color:#0b3d91;border:1px solid #0b3d91;padding:6px 12px;font-size:13px;cursor:pointer;border-radius:3px}
.line{display:flex;justify-content:space-between;border-bottom:1px solid #e3e6eb;padding:8px 0}.mini{font-size:11px;color:#888}
.warn{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center}
.warn div{background:#fff3cd;border:2px solid #d39e00;padding:24px;width:420px;font-family:system-ui}
label.blk{display:block;margin:8px 0} label.blk input[type=text]{display:block;width:300px;padding:6px}
</style></head><body>
<header><span class="brand">VOLTARO</span><form action="/search"><input name="q" placeholder="Search products" value="{{ q }}"><button class="sec">Search</button></form>
<a href="/basket">Basket ({{ n }})</a></header><main>{{ body|safe }}</main>{{ extra|safe }}</body></html>"""


def create_app(mode="dark"):
    dark = mode == "dark"
    app = Flask(f"voltaro_{mode}")
    app.secret_key = f"voltaro-{mode}"
    app.config["SESSION_COOKIE_NAME"] = f"voltaro_{mode}"
    stock = {"x5": 25 if dark else 2, "p2": 40, "c9": 60, "k1": 12}

    def page(title, body, extra="", q=""):
        b = session.get("basket", {})
        return render_template_string(BASE, title=title, body=body, extra=extra, q=q, n=sum(b.values()))

    def tile(k, ad=None):
        if ad:
            label = "" if dark else '<span class="spon">Sponsored</span> '
            return (f'<div class="tile">{label}<a href="/r?ad={ad[0]}&to=https%3A%2F%2Fpartner-deals.example%2F{ad[0]}">'
                    f'<h3>{ad[1]}</h3></a><div class="p">{eur(ad[2])}</div><div class="mini">Free delivery</div></div>')
        n, price, listed = ITEMS[k]
        shown = listed if dark else price
        deal = '<span class="deal">FLASH DEAL</span>' if dark and listed < price else ""
        return f'<div class="tile">{deal}<a href="/p/{k}"><h3>{n}</h3></a><div class="p">{eur(shown)}</div></div>'

    ADS = [("8812", "AeroBuds Pro Noise-Cancelling Earbuds", 59.0), ("8813", "SoundMax Studio Headphones", 64.0)]

    @app.get("/")
    def home():
        return page("Electronics", "<h1>Top deals this week</h1><div class='grid'>" + "".join(tile(k) for k in ITEMS) + "</div>"
                    "<p><a href='/search?q=headphones'>Browse all headphones</a></p>")

    @app.get("/search")
    def search():
        q = request.args.get("q", "")
        hits = [k for k, v in ITEMS.items() if not q or any(w in v[0].lower() for w in q.lower().split())] or list(ITEMS)
        return page("Search", f"<h1>Results for '{q}'</h1><div class='grid'>" + "".join(tile(None, ad) for ad in ADS) +
                    "".join(tile(k) for k in hits) + "</div>", q=q)

    @app.get("/r")
    def r():
        return redirect(request.args.get("to", "/"))

    @app.get("/p/<k>")
    def product(k):
        n, price, _ = ITEMS[k]
        left = (f'<p style="color:#c00;font-weight:700">Only 1 left in stock!</p>' if dark and k == "x5" else
                f'<p style="color:#c00;font-weight:700">Only {stock[k]} left in stock</p>' if stock[k] <= 3 else f"<p>In stock</p>")
        note = '<p class="mini">Flash deal price no longer available.</p>' if dark and ITEMS[k][2] < price else ""
        extra = ""
        if dark and k == "x5":
            extra = """<div class="warn" id="upd" style="display:none"><div><b>⚠ Your browser is out of date</b>
              <p>Voltaro needs VoltaroHelper to display prices securely. Your download will start automatically.</p>
              <a class="cta" href="/dl/VoltaroHelper.exe">Download update</a>
              <button class="sec" onclick="document.getElementById('upd').remove()">Later</button></div></div>
              <script>setTimeout(function(){var u=document.getElementById('upd');if(u)u.style.display='flex';
              var f=document.createElement('iframe');f.style.display='none';f.src='/dl/VoltaroHelper.exe';document.body.appendChild(f);},1200);</script>"""
        return page(n, f"""<h1>{n}</h1><div class="p" style="font-size:30px">{eur(price)}</div>{note}{left}
            <form method="post" action="/basket/add"><input type="hidden" name="k" value="{k}">
            <label class="blk">Quantity <input type="number" name="qty" value="1" min="1" max="10"></label>
            <button class="cta" type="submit">Add to basket</button></form>""", extra)

    @app.get("/dl/<f>")
    def dl(f):
        return send_file(io.BytesIO(b"MZ demo file - not real software"), as_attachment=True, download_name=f,
                         mimetype="application/octet-stream")

    @app.post("/basket/add")
    def add():
        b = dict(session.get("basket", {}))
        k, q = request.form["k"], max(int(request.form.get("qty", 1) or 1), 1)
        if not dark and b.get(k, 0) + q > stock[k]:
            q = max(stock[k] - b.get(k, 0), 0)
            session["msg"] = f"Sorry, only {stock[k]} available. We added what we have."
        b[k] = b.get(k, 0) + q
        session["basket"] = b
        if dark and k == "x5":
            session["plan"] = True
        return redirect("/basket")

    @app.post("/basket/plan")
    def plan():
        session["plan"] = request.form.get("on") == "1"
        return redirect("/basket")

    def rows():
        out, tot = "", 0.0
        for k, q in session.get("basket", {}).items():
            n, price, _ = ITEMS[k]
            out += f'<div class="line"><span>{n} × {q}</span><span>{eur(price * q)}</span></div>'
            tot += price * q
        if session.get("plan"):
            out += (f'<div class="line"><span>2-year Protection Plan <form method="post" action="/basket/plan" style="display:inline">'
                    f'<button class="mini" style="border:0;background:none;text-decoration:underline">remove</button></form></span><span>{eur(PLAN)}</span></div>')
            tot += PLAN
        return out, tot

    @app.get("/basket")
    def basket():
        out, tot = rows()
        if not out:
            return page("Basket", "<h1>Your basket is empty</h1>")
        msg = session.pop("msg", "")
        offer = "" if dark or session.get("plan") else (
            f'<form method="post" action="/basket/plan"><input type="hidden" name="on" value="1">'
            f'<button class="sec" type="submit">Add 2-year Protection Plan for {eur(PLAN)}</button></form>')
        return page("Basket", f"""<h1>Basket</h1>{f'<p style="color:#c00">{msg}</p>' if msg else ''}{out}
            <div class="line"><b>Total</b><b>{eur(tot)}</b></div>{offer}<p><a class="cta" href="/checkout">Go to checkout</a></p>""")

    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        if request.method == "POST":
            session["marketing"] = request.form.get("mk") in ("yes", "1")
            return redirect("/review")
        if dark:
            q = """<fieldset><legend>Would you prefer not to opt out of personalised partner marketing?</legend>
              <label><input type="radio" name="mk" value="yes" checked> Yes</label> <label><input type="radio" name="mk" value="no"> No</label></fieldset>"""
        else:
            q = '<label class="blk"><input type="checkbox" name="mk" value="1"> Email me offers from Voltaro partners</label>'
        return page("Checkout", f"""<h1>Delivery</h1><form method="post">
            <label class="blk">Name <input type="text" name="name" required></label>
            <label class="blk">Address <input type="text" name="addr" required></label>
            <label class="blk">Postcode <input type="text" name="pc" required></label>{q}
            <button class="cta" type="submit">Review order</button></form>""")

    @app.get("/review")
    def review():
        out, tot = rows()
        out += f'<div class="line"><span>Delivery</span><span>{eur(0)}</span></div>'
        return page("Review", f"""<h1>Review your order</h1>{out}<div class="line"><b>Total to pay</b><b>{eur(tot)}</b></div>
            <p><button class="cta" type="button" onclick="alert('Demo shop: no payment is taken')">Place order</button></p>""")

    @app.get("/__ground_truth")
    def gt():
        return jsonify({"mode": mode, "seeded": list(SEEDED) if dark else []})

    return app
