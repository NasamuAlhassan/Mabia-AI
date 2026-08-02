"""The nutrition engine.

Measuring a diet is easy. Giving advice a household can act on is the hard part,
and it is the part the evidence says is missing. So this engine never
recommends a food in the abstract: it recommends against the gap it just
measured, filtered by the region, the month, what the household can afford, and
what it will not eat.

It returns exactly one message. Never a list -- on a GSM line, a caregiver will
remember one thing, and a list of five is a list of none.
"""
import datetime as dt
from typing import Dict, List, Optional

from ..data.foods import (AFFORDABILITY_CEILING, CHILD_MINIMUM, FOODS,
                          MDDW_MINIMUM, TIERS, group_labels, groups_for,
                          GROUP_WHY, HYDRATION_NOTE, season_for, tier_for)

MDD_W = "mdd_w"
MDD_CHILD = "mdd_child"


class Recall:
    """The result of asking the food-group questions."""

    def __init__(self, instrument: str, present: List[str]):
        self.instrument = instrument
        all_groups = groups_for(instrument)
        self.present = [g for g in present if g in all_groups]
        self.missing = [g for g in all_groups if g not in self.present]
        self.score = len(self.present)
        self.total = len(all_groups)
        self.minimum = MDDW_MINIMUM if instrument == MDD_W else CHILD_MINIMUM

    @property
    def meets_minimum(self) -> bool:
        return self.score >= self.minimum

    def to_dict(self):
        labels = group_labels(self.instrument)
        return {
            "instrument": self.instrument,
            "score": self.score,
            "total": self.total,
            "minimum": self.minimum,
            "meets_minimum": self.meets_minimum,
            "present": self.present,
            "missing": self.missing,
            "missing_labels": [labels[g] for g in self.missing],
        }


class Recommendation:
    def __init__(self, food, group, season, message, reason, alternatives=None,
                 anaemia_tip=None):
        self.food = food
        self.group = group
        self.season = season
        self.message = message
        self.reason = reason
        self.alternatives = alternatives or []
        self.anaemia_tip = anaemia_tip

    @property
    def why(self):
        return GROUP_WHY.get(self.group, "")

    def to_dict(self):
        return {
            "why": self.why,
            "hydration": HYDRATION_NOTE,
            "food_key": self.food["key"] if self.food else None,
            "food_name": self.food["name"] if self.food else None,
            "local_names": self.food.get("local_names", {}) if self.food else {},
            "group": self.group,
            "season": self.season,
            "tier": self.food["tier"] if self.food else None,
            "source": self.food["source"] if self.food else None,
            "message": self.message,
            "reason": self.reason,
            "alternatives": [f["name"] for f in self.alternatives],
            "anaemia_tip": self.anaemia_tip,
        }


# Free advice that costs the household nothing and is widely unknown. Attached
# whenever iron is the concern, which -- at 44.2% maternal anaemia in the Upper
# West -- is often.
ANAEMIA_TIPS = [
    "Do not drink tea with meals. It blocks the body from taking in iron.",
    "Eat something sour or citrus with the beans — it helps the iron get in.",
    "Keep taking the iron and folic acid tablets, even when you feel well.",
]


def _group_key_for(food, instrument: str) -> List[str]:
    return food["w_groups"] if instrument == MDD_W else food["c_groups"]


def _available(food, month: int, region: str) -> bool:
    if month not in food["months"]:
        return False
    if food["regions"] != "all" and region not in food["regions"]:
        return False
    return True


def _affordable(food, affordability: str, season: str) -> bool:
    return tier_for(food, season) in AFFORDABILITY_CEILING.get(affordability, TIERS)


# Not every gap is worth the same. A household short of flesh foods, dark
# leaves or vitamin A is short of the things that actually drive anaemia and
# stunting; one short of "other fruit" is not. Filling the cheapest gap every
# time would be easy and useless.
GROUP_PRIORITY = {
    "flesh": 10, "dark_leafy": 8, "vita_fruit_veg": 8,
    "pulses": 7, "pulses_nuts_seeds": 7, "nuts_seeds": 6,
    "eggs": 6, "dairy": 5,
    "other_fruit_veg": 3, "other_veg": 2, "other_fruit": 2,
    "grains": 1, "breastmilk": 10,
}


def _score_food(food, season: str, anaemia_focus: bool) -> float:
    """Within a chosen gap: which food is easiest for THIS household, THIS month."""
    score = float(TIERS.index(tier_for(food, season))) * 4.0
    source_penalty = {"gathered": 0, "stored": 1, "grown": 2, "purchased": 4}
    weight = 3.0 if season == "lean" else 1.0
    score += source_penalty.get(food["source"], 3) * weight
    if anaemia_focus and food["iron_rich"]:
        score -= 5.0
    if anaemia_focus and food["vitamin_c"]:
        score -= 2.0
    return score


def recommend(
    recall: Recall,
    *,
    region: str = "Northern",
    month: Optional[int] = None,
    affordability: str = "low",
    taboos: Optional[List[str]] = None,
    anaemia_focus: bool = False,
    exclude: Optional[List[str]] = None,
    recent_groups: Optional[List[str]] = None,
) -> Optional[Recommendation]:
    """Pick one food that fills a gap and can actually be obtained."""
    month = month or dt.date.today().month
    season = season_for(month)
    taboos = set(taboos or [])
    # Do not repeat last call's advice; a caregiver who hears the same
    # sentence every fortnight stops hearing it.
    exclude = set(exclude or [])
    recent_groups = set(recent_groups or [])

    if not recall.missing:
        return Recommendation(
            None, None, season,
            "Her diet covered every food group this time. Tell her so — and ask "
            "her to keep it up.",
            "no gaps measured")

    # Pick the GAP first, then the best food within it.
    #
    # Scoring every food across every gap together meant one free, year-round,
    # iron-rich item won permanently: a woman missing seven food groups heard
    # the same sentence at every contact, in every month of the year. Working
    # through her gaps in order of clinical importance is both better advice and
    # the thing that lets the season become visible at all.
    def gap_options(group):
        out = []
        for food in FOODS:
            if group not in _group_key_for(food, recall.instrument):
                continue
            if not _available(food, month, region):
                continue
            if not _affordable(food, affordability, season):
                continue
            # A taboo is not argued with on an automated call. The food is
            # dropped and the next best in the SAME group is offered instead.
            if food["key"] in taboos or food["key"] in exclude:
                continue
            out.append((_score_food(food, season, anaemia_focus), food))
        out.sort(key=lambda c: (c[0], c[1]["key"]))
        return out

    ordered = sorted(recall.missing, key=lambda g: (-GROUP_PRIORITY.get(g, 3), g))
    # Groups already covered by recent advice go to the back of the queue.
    queue = ([g for g in ordered if g not in recent_groups]
             + [g for g in ordered if g in recent_groups])

    group, options = None, []
    for candidate_group in queue:
        options = gap_options(candidate_group)
        if options:
            group = candidate_group
            break

    if group is None:
        # Nothing she can reach fills what is left. If she is already above the
        # minimum that is a good result, not an escalation -- the remaining gaps
        # are foods this household genuinely cannot buy, and telling her to buy
        # eggs she cannot afford is how nutrition advice loses its audience.
        if recall.meets_minimum:
            return Recommendation(
                None, None, season,
                "Her diet is varied enough this time. Tell her so — the foods "
                "still missing are ones this household cannot easily afford.",
                "above the minimum; remaining gaps are out of reach")
        return Recommendation(
            None, None, season,
            "No affordable local food fills her gaps this month. This needs a "
            "home visit rather than a phone message.",
            "no reachable food for the measured gaps — escalated to the CHO")

    best = options[0][1]
    alternatives = [food for _, food in options[1:3]]
    labels = group_labels(recall.instrument)
    reason = "{} missing; {} season in {}; {} costs {} now".format(
        labels.get(group, group), season, region, best["name"].lower(),
        tier_for(best, season))

    tip = None
    if anaemia_focus:
        tip = ANAEMIA_TIPS[0] if not best["vitamin_c"] else ANAEMIA_TIPS[1]

    return Recommendation(best, group, season, best["message"], reason,
                          alternatives, tip)


def instrument_for(subject: str) -> str:
    """Which instrument applies to whom. These are never interchangeable."""
    return MDD_W if subject in ("mother", "woman") else MDD_CHILD


def questions(instrument: str) -> List[Dict[str, str]]:
    """The keypad questions, in order, one food group each."""
    labels = group_labels(instrument)
    out = []
    for key in groups_for(instrument):
        out.append({"group": key, "label": labels[key],
                    "prompt": _PROMPTS.get(key, "Did you eat {}?".format(labels[key]))})
    return out


_PROMPTS = {
    "breastmilk": "Did the child take breast milk yesterday?",
    "grains": "Did you eat porridge, tuo zaafi, rice or yam yesterday?",
    "pulses": "Did you eat beans or bambara yesterday?",
    "nuts_seeds": "Did you eat groundnut or dawadawa yesterday?",
    "pulses_nuts_seeds": "Did the child eat beans or groundnut yesterday?",
    "dairy": "Did you take milk yesterday?",
    "flesh": "Did you eat fish or meat yesterday, even dried fish?",
    "eggs": "Did you eat an egg yesterday?",
    "dark_leafy": "Did you eat green leaves yesterday, like ayoyo or baobab leaf?",
    "vita_fruit_veg": "Did you eat mango, pawpaw or orange sweet potato yesterday?",
    "other_veg": "Did you eat okra, tomato or garden egg yesterday?",
    "other_fruit": "Did you eat any other fruit yesterday?",
    "other_fruit_veg": "Did the child eat any other fruit or vegetable yesterday?",
}
