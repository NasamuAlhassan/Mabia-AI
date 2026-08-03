"""Everything the platform ever says out loud, in English.

Assembled from the actual sources rather than kept as a second copy, so a new
danger-sign question or a new food automatically appears in the translation and
recording queues instead of being quietly forgotten.
"""
from typing import Dict, List

from .. import prompts
from ..data.foods import FOODS
from ..engines.nutrition import ANAEMIA_TIPS
from ..engines.nutrition import MDD_CHILD, MDD_W, questions

# Lines that are never spoken to a caller on their own.
SKIP = {"escape_hint"}


def catalogue() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    # Greeting and consent are one breath. The escape hint is deliberately not
    # part of it: together they run past the synthesis ceiling, and telling her
    # about pressing 9 before she has agreed to talk is telling her too early.
    out.append({
        "key": "greet_consent", "category": "script",
        "text": "{} {}".format(prompts.line("greet"), prompts.line("consent"))})
    out.append({
        "key": "escape_hint", "category": "script",
        "text": prompts.line("escape_hint")})

    for key, text in prompts.DANGER_QUESTIONS:
        out.append({"key": "danger_" + key, "category": "script", "text": text})

    bkey, btext = prompts.BIRTH_PLAN_QUESTION
    out.append({"key": bkey, "category": "script", "text": btext})

    for key, text in prompts.SCRIPT.items():
        if key in SKIP or key in ("greet", "consent"):
            continue
        out.append({"key": key, "category": "script", "text": text})

    seen = set()
    for instrument in (MDD_W, MDD_CHILD):
        for question in questions(instrument):
            key = "diet_" + question["group"]
            if key in seen:
                continue
            seen.add(key)
            out.append({"key": key, "category": "diet",
                        "text": question["prompt"]})

    # The personalised half. These are why an API is needed at all: the message
    # a household hears depends on its gaps, its region and the month, so there
    # is no fixed set to pre-record by hand.
    for food in FOODS:
        out.append({"key": "food_" + food["key"], "category": "food",
                    "text": food["message"]})
        # Only where the wording for the woman herself genuinely differs from
        # the caregiver wording. Emitting a duplicate line for the other
        # twenty-eight foods would be work for a recordist and nothing else.
        if food["mother_message"] != food["message"]:
            out.append({"key": "food_" + food["key"] + "_mother",
                        "category": "food", "text": food["mother_message"]})

    # The anaemia tips ride alongside the food advice on the same turn. They
    # were the only spoken lines in the system with no catalogue entry, so they
    # could never be translated and never be recorded -- and at 44.2% maternal
    # anaemia in the Upper West they are said on a great many calls.
    for index, tip in enumerate(ANAEMIA_TIPS):
        out.append({"key": "anaemia_tip_{}".format(index + 1),
                    "category": "nutrition", "text": tip})

    return out


def by_key() -> Dict[str, Dict[str, str]]:
    return {row["key"]: row for row in catalogue()}
