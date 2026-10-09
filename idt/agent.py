"""Simulated users. Both get the same plain-English intent and no site-specific hints.

careful : an LLM agent that reads everything, declines what it did not ask for and does only what the goal
          needs. Its action log is the record of what the user chose.
hurried : bounded attention. It fills only what it must, never changes a pre-set option, and among the
          controls that plausibly move it forward clicks the most visually dominant one (salience is computed
          from the DOM, not chosen by the model).

Whatever the hurried user ends up with that the careful one avoided is the manipulation delta.
"""
from harness import llm
from .perceive import render

PROFILE = {"name": "Test User", "first name": "Test", "last name": "User", "email": "idt.audit@example.com",
           "phone": "9876543210", "address": "12 MG Road", "city": "Bengaluru", "state": "Karnataka",
           "postcode/zip": "560001", "country": "India", "password": "Audit#2026xq", "company": "none"}

ACT_SCHEMA = {"type": "object", "required": ["actions", "status", "reason"], "properties": {
    "actions": {"type": "array", "items": {"type": "object", "required": ["do", "id"], "properties": {
        "do": {"type": "string", "enum": ["click", "fill", "check", "uncheck", "select"]},
        "id": {"type": "string"}, "value": {"type": "string"}}}},
    "status": {"type": "string", "enum": ["continue", "done", "blocked"]},
    "evidence": {"type": "string"}, "forced": {"type": "string"}, "reason": {"type": "string"}}}

CAREFUL_RULES = (
    "You are a careful, privacy-conscious user. Read everything on the screen. Do only what your goal needs.\n"
    "- Untick or decline anything you did not ask for: paid extras, protection plans, upgrades, trials, memberships, "
    "marketing or partner consents, newsletters, auto-renew. Read consent wording carefully, including negations, and "
    "set each box so that you do NOT receive optional things.\n"
    "- Close popups that are not part of your goal. For cookie banners choose the most privacy-protective option "
    "(reject all / necessary only); if that needs a settings screen, use it.\n"
    "- If the site requires something unrelated to your goal (creating an account when buying, joining a newsletter, "
    "installing an app), first try to continue without it. Only if there is no other way, do it, and describe it in "
    "`forced`.\n"
    "- Fill required form fields with the TEST PROFILE.\n")
HURRIED_RULES = (
    "You are a hurried user who skims. Fill ONLY empty fields that are marked required, using the TEST PROFILE. "
    "Never untick, uncheck or change anything that is already selected. Then click whatever gets you forward fastest.\n")
COMMON = (
    "- Never click anything that pays, places an order or submits card details; the audit stops before payment.\n"
    "- status=done when the goal is visibly achieved on this screen (quote the text that shows it in `evidence`); "
    "blocked if you cannot make progress.\n"
    "- Actions run in order; put at most one click, and put it last. On a form, fill EVERY field you need in the same "
    "answer as the click that submits it.\n")


class Persona:
    name = "?"

    def __init__(self, intent: str, readonly: bool = False):
        self.intent = intent
        self.readonly = readonly
        self.history = []
        self.clicks = {}
        self.refused = False      # set by the journey runner when the site refused the last attempt

    def _ask(self, snap, rules, extra=""):
        hist = "\n".join(self.history[-8:]) or "(start)"
        pops = "\n".join(f"popup#{o['idx']}: {o['text'][:250]!r}" for o in snap["overlays"]) or "(none)"
        ro = ("- READ-ONLY AUDIT of a real website: do not create accounts, log in, subscribe or submit personal data. "
              "If the next step needs any of these, set status=done with evidence 'reached <what>'.\n") if self.readonly else ""
        last = next((h for h in reversed(self.history[-3:]) if h.startswith("SITE REFUSED")), "")
        warn = (f"\nIMPORTANT: your last attempt was refused by the site: {last}\nFix exactly what it asks. If it demands "
                "something unrelated to your goal and there is no other way forward, comply and describe it in `forced`.\n") if last else ""
        prompt = (f"YOUR GOAL: {self.intent}\n\n{rules}{COMMON}{ro}{extra}{warn}\nTEST PROFILE: {PROFILE}\n\n"
                  f"SCREEN {snap['url']}\nPOPUPS:\n{pops}\n\nPAGE TEXT:\n{snap['text'][:2500]}\n\nCONTROLS:\n{render(snap)}\n\n"
                  f"YOUR STEPS SO FAR:\n{hist}\n\nGive the actions for this screen. Keep reason under 25 words.")
        # right after a refusal the decision is harder (comply? which field?): let the model reason
        j = llm.ask_json(prompt, task="navigation", schema=ACT_SCHEMA, think=bool(last))
        acts = [a for a in j.get("actions", []) if a.get("id") in snap["by_id"]]
        clicks = [a for a in acts if a["do"] == "click"]
        acts = [a for a in acts if a["do"] != "click"] + clicks[:1]
        if j.get("status") == "continue" and not clicks:
            j2 = llm.ask_json(prompt + "\n\nYour previous answer had no valid click but your goal is not done. Choose the "
                              "control id that moves you towards it, or set status=blocked.", task="navigation", schema=ACT_SCHEMA)
            c2 = [a for a in j2.get("actions", []) if a.get("do") == "click" and a.get("id") in snap["by_id"]]
            if c2:
                acts, j = acts + c2[:1], j2
        return acts, j

    def _remember(self, snap, acts, j):
        for a in acts:
            el = snap["by_id"][a["id"]]
            self.history.append(f"{snap['url']}: {a['do']} {el['name'] or el['field']!r}" + (f" = {a.get('value')!r}" if a.get("value") else ""))
            if a["do"] == "click":
                key = (snap["url"], el["name"])
                self.clicks[key] = self.clicks.get(key, 0) + 1


class Careful(Persona):
    name = "careful"

    def decide(self, snap, ann):
        acts, j = self._ask(snap, CAREFUL_RULES)
        for a in acts:
            if a["do"] == "click" and self.clicks.get((snap["url"], snap["by_id"][a["id"]]["name"]), 0) >= 3:
                return [], {**j, "status": "blocked", "reason": f"repeating '{snap['by_id'][a['id']]['name']}' without progress"}
        self._remember(snap, acts, j)
        return acts, j


class Hurried(Persona):
    name = "hurried"

    def decide(self, snap, ann):
        by = snap["by_id"]
        # popups: cookie banners get the most prominent button; other popups get closed if there is a close control
        for p in ann["popups"]:
            inside = [e for e in snap["elements"] if e["region"] == f"popup#{p['popup']}" and e["kind"] in ("button", "link")]
            if p["kind"] == "cookie_consent" and inside:
                top = max(inside, key=lambda e: e["salience"])
                acts = [{"do": "click", "id": top["id"]}]
                self._remember(snap, acts, {})
                return acts, {"status": "continue", "reason": f"most prominent cookie-banner button ('{top['name']}')"}
            target = p.get("dismiss_id") or p.get("reject_id")
            if target and self.clicks.get((snap["url"], by[target]["name"]), 0) < 2:
                acts = [{"do": "click", "id": target}]
                self._remember(snap, acts, {})
                return acts, {"status": "continue", "reason": "closes the popup"}
        acts, j = self._ask(snap, HURRIED_RULES)
        keep = []
        for a in acts:
            el = by[a["id"]]
            if a["do"] == "fill" and (el["required"] or self.refused) and not el["value"]:
                keep.append(a)
            elif a["do"] in ("check", "select") and (el["required"] or self.refused):
                keep.append(a)      # after a refusal, a hurried user does what the error message demands
        self.refused = False
        mine = next((a for a in acts if a["do"] == "click"), None)
        if mine and (ann["page_kind"] in ("home", "listing") or mine["id"] in {c["id"] for c in ann["product_cards"]}):
            # finding the product they came for is not where steering happens; they click what they were looking for
            keep.append(mine)
            self._remember(snap, keep, j)
            return keep, j
        # the click is chosen by salience among everything that plausibly moves forward
        cards = {c["id"] for c in ann["product_cards"]}
        cands = set(ann["forward"]) | set(ann["offers"]) | set(ann["declines"]) | {a["id"] for a in acts if a["do"] == "click"}
        own = {a["id"] for a in acts if a["do"] == "click"}
        cands = [by[i] for i in cands if ((by[i]["region"] in ("main",) or by[i]["region"].startswith("popup")) and i not in cards)
                 or i in own]       # the user's own pick counts even in the site header (e.g. the cart link)
        cands = [e for e in cands if self.clicks.get((snap["url"], e["name"]), 0) < 2]
        reason = j.get("reason", "")
        if cands and j.get("status") != "done":     # a hurried user keeps going rather than stopping to think
            top = max(cands, key=lambda e: e["salience"])
            keep.append({"do": "click", "id": top["id"]})
            reason = f"most visually dominant way forward ('{top['name']}', salience {top['salience']})"
        self._remember(snap, keep, j)
        status = "continue" if any(k["do"] == "click" for k in keep) and j.get("status") != "done" else j.get("status")
        return keep, {**j, "reason": reason, "status": status}
