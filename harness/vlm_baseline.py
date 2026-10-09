"""Screenshot-VLM baseline: a local vision-language model judges each screen on its own.

This is the approach most recent work takes (a VLM shown a screenshot and asked "which dark patterns are
here?"). It gets the same screens the journeys visited, one at a time, with the CCPA category definitions.
It is a fair baseline: it can read copy, see pre-ticked boxes and judge visual dominance. What it cannot
do is compare a screen with another screen, session or system of record.
"""
from . import llm

DEFS = {
    "false_urgency": "a countdown, deadline or 'limited time' claim pressuring the user to act now",
    "false_scarcity": "a low-stock or high-demand claim ('only 2 left', '20 people viewing')",
    "basket_sneaking": "a paid item or add-on included or pre-selected without the user choosing it",
    "drip_pricing": "fees or charges added on top of the price that was first shown",
    "interface_interference": "design that steers the user to an option (e.g. a dominant offer button, a hidden plain option)",
    "confirm_shaming": "decline wording that uses guilt or ridicule ('No thanks, I hate saving money')",
    "trick_question": "confusingly worded consent, e.g. double negatives, pre-ticked consent",
    "subscription_trap": "a membership that is easy to join but hard to cancel, or a cancel flow that obstructs",
    "nagging": "a prompt that repeatedly interrupts the user",
}
SCHEMA = {"type": "object", "required": ["patterns"], "properties": {"patterns": {"type": "array", "items": {
    "type": "object", "required": ["category", "evidence"], "properties": {
        "category": {"type": "string", "enum": list(DEFS)}, "evidence": {"type": "string"}}}}}}
PROMPT = ("You are an auditor for India's CCPA Guidelines for Prevention and Regulation of Dark Patterns (2023). "
          "Look at this one screenshot of a shopping website and list every dark pattern you can see on it, "
          "using only these categories:\n" + "\n".join(f"- {k}: {v}" for k, v in DEFS.items()) +
          "\nFor each, give the visible evidence. If the screen is honest, return an empty list.")


def recognise(screens):
    """screens: trace steps with 'url' and 'shot' (base64 JPEG). One VLM call per distinct screen."""
    model = llm.vision_model()
    if not model:
        return None
    seen, hits = set(), {}
    for s in screens:
        if not s.get("shot") or s["url"] in seen:
            continue
        seen.add(s["url"])
        try:
            j = llm.ask_json(PROMPT, task="VLM screenshot baseline", schema=SCHEMA, images=[s["shot"]], model=model)
        except Exception:
            continue
        for p in j.get("patterns", []):
            if p.get("category") in DEFS:
                hits.setdefault(p["category"], []).append(f"{s['url']}: {p.get('evidence', '')}")
    return {k: sorted(set(v)) for k, v in hits.items()}
