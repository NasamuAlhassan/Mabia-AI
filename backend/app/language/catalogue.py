"""Everything the platform ever says out loud, in English.

Assembled from the actual sources rather than kept as a second copy, so a new
danger-sign question or a new food automatically appears in the translation and
recording queues instead of being quietly forgotten.
"""
from typing import Dict, List

from .. import prompts
from ..data.foods import FOODS
from ..engines.nutrition import MDD_CHILD, MDD_W, questions

# Lines that are never spoken to a caller — internal or English-only.
SKIP = {"escape_hint"}


def catalogue() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    # The greeting is spoken as one breath, so it is one clip.
    out.append({
        "key": "greet_consent", "category": "script",
        "text": "{} {} {}".format(prompts.line("greet"), prompts.line("consent"),
                                  prompts.line("escape_hint"))})

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

    return out


def by_key() -> Dict[str, Dict[str, str]]:
    return {row["key"]: row for row in catalogue()}
