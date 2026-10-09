"""Vision fallback for navigation. When the text-reading agent stalls (a click did nothing, or it says it is
blocked), the screen is shown to a local vision model with every control outlined and labelled (set-of-marks),
and it picks by what it sees. Popups, modals and custom widgets that confuse a text view are usually obvious
in a picture. The model only picks an element; the journey still records what actually happened.
"""
from harness import llm

SCHEMA = {"type": "object", "required": ["label", "reason"], "properties": {
    "label": {"type": "string"}, "reason": {"type": "string"}}}


def rescue(tab, snap, intent: str, history: list) -> dict | None:
    model = llm.vision_model()
    if not model:
        return None
    img, shown = tab.marked_shot()
    if not shown:
        return None
    try:
        j = llm.ask_json(
            f"You are helping a shopper who is stuck on a website. Their goal: {intent}\n"
            f"What they did so far (latest last):\n" + "\n".join(history[-8:]) + "\n\n"
            "The screenshot shows the current screen. Every clickable control has a red outline with a red label "
            "such as e12. Which ONE label should be clicked next to make progress? If a popup or dialog is open, deal "
            "with it first (for example 'View cart', 'Continue', or close it). Never choose anything that pays or "
            f"places an order. Valid labels: {', '.join(shown[:150])}",
            task="vision rescue", schema=SCHEMA, images=[img], model=model)
    except Exception:
        return None
    if j.get("label") in snap["by_id"] and j["label"] in shown:
        return {"do": "click", "id": j["label"], "reason": j.get("reason", "")}
    return None
