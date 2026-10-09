"""Cross-session and cross-flow checks that a single screenshot cannot make:
falsity of urgency/scarcity claims, friction asymmetry, and nagging."""
import re
import time

import requests

from . import llm
from .browser import observe, shot, dismiss_dialog, click_candidate, pick_radio, read_kv
from .personas import Agent, Careful, Intent

TIMER_RE = re.compile(r"ends in\s*((?:\d+:)?\d{1,2}:\d{2})", re.I)
STOCK_RE = re.compile(r"only\s+(\d+)\s+left", re.I)


def _secs(t: str) -> int:
    parts = [int(x) for x in t.split(":")]
    s = 0
    for p in parts:
        s = s * 60 + p
    return s


# ---------------------------------------------------------------- falsity
def _claims(text: str):
    """(timer text, stock units, extracted_by, quotes). The local LLM finds claims however they are phrased; its quotes
    are grounded against the page. The regexes are the fallback and only know 'ends in' / 'only N left'."""
    if llm.available():
        try:
            cl = llm.extract_claims(text)
            tm = next((c for c in cl if c["kind"] == "countdown" and re.fullmatch(r"(\d+:)?\d{1,2}:\d{2}",
                                                                                 (c.get("displayed_time") or "").strip())
                       and c["displayed_time"].strip() in text), None)
            st = next((c for c in cl if c["kind"] == "stock_count" and isinstance(c.get("units"), int)
                       and str(c["units"]) in c["quote"]), None)
            return (tm["displayed_time"].strip() if tm else None, st["units"] if st else None,
                    llm.backend_name(), [c["quote"] for c in cl])
        except Exception:
            pass
    tm, st = TIMER_RE.search(text), STOCK_RE.search(text)
    return tm.group(1) if tm else None, int(st.group(1)) if st else None, "regex", []


def falsity(browser, base: str, product_path: str, inventory_api: str | None, sessions: int = 3, gap: float = 3.0):
    """Visit the product in several fresh sessions over time. A genuine deadline is the same wall-clock
    moment for everyone; a fake one moves with each visit. A stock claim is checked against the
    client's inventory system of record when one is configured."""
    obs_list = []
    for i in range(sessions):
        ctx = browser.new_context(viewport={"width": 1100, "height": 760})
        p = ctx.new_page()
        p.goto(base + product_path)
        dismiss_dialog(p)
        time.sleep(1.2)                      # let the on-page countdown render
        t_obs = time.time()
        text = observe(p)["text"]
        tm, st, by, quotes = _claims(text)
        rec = {"session": i + 1, "observed_at": t_obs, "timer": tm, "stock_claim": st, "extracted_by": by,
               "quotes": quotes, "shot": shot(p) if i == 0 else None}
        if tm:
            # the model only read the timer; the deadline arithmetic is ours
            rec["implied_deadline"] = t_obs + _secs(tm)
        obs_list.append(rec)
        ctx.close()
        if i < sessions - 1:
            time.sleep(gap)
    out = {"observations": obs_list, "timer": None, "stock": None}
    deadlines = [o["implied_deadline"] for o in obs_list if "implied_deadline" in o]
    if deadlines:
        spread = max(deadlines) - min(deadlines)
        elapsed = obs_list[-1]["observed_at"] - obs_list[0]["observed_at"]
        out["timer"] = {"deadline_spread_s": round(spread, 1), "elapsed_s": round(elapsed, 1),
                        "verdict": "false" if spread > 3 else "consistent",
                        "explanation": (f"Implied deadline moved {spread:.0f}s across {len(deadlines)} sessions "
                                        f"{elapsed:.0f}s apart: the countdown restarts per visit, so the deadline is not real."
                                        if spread > 3 else
                                        f"Every session pointed to the same deadline (±{spread:.0f}s): the countdown is genuine.")}
    claims = [o["stock_claim"] for o in obs_list if o["stock_claim"] is not None]
    if claims:
        sor = None
        if inventory_api:
            try:
                sor = requests.get(base + inventory_api, timeout=5).json().get("units_available")
            except Exception:
                sor = None
        if sor is None:
            out["stock"] = {"claim": claims[0], "inventory": None, "verdict": "unverified",
                            "explanation": "Stock claim cannot be proven true or false without an inventory oracle."}
        else:
            ok = all(c == sor for c in claims)
            out["stock"] = {"claim": claims[0], "inventory": sor, "verdict": "consistent" if ok else "false",
                            "explanation": (f"Page claims 'only {claims[0]} left'; inventory system of record holds {sor}."
                                            if not ok else f"Claim of {claims[0]} matches inventory ({sor}).")}
    return out


# ---------------------------------------------------------------- friction
def _goal_flow(page, base, account_path, intent, done, persona=Careful) -> dict:
    page.goto(base + account_path)
    agent = persona()
    actions, pages, nags, path = 0, [], 0, []
    for _ in range(14):
        if dismiss_dialog(page):
            nags += 1
        obs = observe(page)
        pages.append(obs["url"])
        acc_rows = {r[0]: r[1] for r in obs["rows"]}
        if done(acc_rows) and actions > 0:
            return {"actions": actions, "screens": len(set(pages)), "nag_dismissals": nags, "path": path,
                    "completed": True}
        d = agent.decide(obs, intent)
        for name in d.radio:
            pick_radio(page, name)
            actions += 1
            path.append(f"{obs['url']}: answer '{name}'")
        if d.click is None:
            break
        c = next(x for x in obs["candidates"] if x["idx"] == d.click)
        path.append(f"{obs['url']}: '{c['text']}'")
        click_candidate(page, d.click)
        actions += 1
    return {"actions": actions, "screens": len(set(pages)), "nag_dismissals": nags, "path": path, "completed": False}


JOIN = Intent(goal_words={"join": 3, "start membership": 3, "subscribe": 3}, avoid_words=(),
              description="Join the shop's paid membership programme.")
CANCEL = Intent(goal_words={"cancel": 3, "continue cancelling": 2, "confirm": 1, "manage membership": 1, "next": 1},
                avoid_words=("keep", "back", "stay"),
                description="Cancel your paid membership. Do not accept discounts or retention offers; "
                            "keep going until it is actually cancelled.")


def _join_cancel(browser, base, account_path, member_key, none_value, persona):
    ctx = browser.new_context(viewport={"width": 1100, "height": 760})
    page = ctx.new_page()
    join = _goal_flow(page, base, account_path, JOIN, lambda a: a.get(member_key, none_value) != none_value, persona)
    cancel = _goal_flow(page, base, account_path, CANCEL, lambda a: a.get(member_key) == none_value, persona)
    ctx.close()
    ratio = cancel["actions"] / max(join["actions"], 1)
    return {"join": join, "cancel": cancel, "ratio": round(ratio, 2),
            "verdict": "asymmetric" if ratio > 1.5 or not cancel["completed"] else "symmetric"}


def friction(browser, base: str, account_path: str, member_key="Membership", none_value="Not a member"):
    """Scripted agent decides the verdict. When a local LLM is available the same flows are repeated by the
    LLM agent from the plain-English goal alone, as an independent count that needs no site-specific words."""
    out = _join_cancel(browser, base, account_path, member_key, none_value, Careful)
    if llm.available():
        out["agent"] = _join_cancel(browser, base, account_path, member_key, none_value, Agent)
    return out


# ---------------------------------------------------------------- nagging
def nagging(browser, base: str, paths: list[str]):
    ctx = browser.new_context(viewport={"width": 1100, "height": 760})
    page = ctx.new_page()
    page.goto(base + paths[0])
    first = dismiss_dialog(page)
    reappeared, evidence = [], None
    for p in paths[1:]:
        page.goto(base + p)
        dlg = page.locator("[role=dialog]")
        if dlg.count() and dlg.first.is_visible():
            reappeared.append(p)
            if evidence is None:
                evidence = shot(page)
            dismiss_dialog(page)
    ctx.close()
    return {"shown_first_visit": first, "pages_after_dismissal": len(paths) - 1,
            "reappeared_on": reappeared, "verdict": "nagging" if reappeared else "respects dismissal",
            "shot": evidence}
