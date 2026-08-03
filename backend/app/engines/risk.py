"""The risk engine.

Deterministic and auditable. It classifies and explains; it never decides. Every
escalation it produces is a proposal that a named human confirms.

Reasons are emitted as **codes**, not English sentences, so that the same
classification renders in Dagbani on a handset and in English on a dashboard
without the engine knowing which. The English strings here are the fallback
rendering, not the value.

Thresholds follow Ghana Health Service and WHO practice:
  mother MUAC  < 23.0 cm   undernutrition in pregnancy
  child  MUAC  < 12.5 cm   moderate acute malnutrition
  child  MUAC  < 11.5 cm   severe acute malnutrition -> CMAM referral
  MDD-W        >= 5 of 10  women of reproductive age
  child MDD    >= 5 of 8   children 6-23 months
"""
from typing import List, Optional

GREEN = "green"
AMBER = "amber"
RED = "red"

_ORDER = {GREEN: 0, AMBER: 1, RED: 2}

# Danger signs that are an emergency on their own. These are the ones where the
# cost of waiting for a second signal is a life.
RED_SIGNS = {
    "bleeding": "Severe vaginal bleeding",
    "convulsions": "Convulsions or fits",
    "severe_headache": "Severe headache with blurred vision",
    "reduced_fetal_movement": "Baby has stopped moving or moves much less",
    "water_broken": "Waters broken without labour",
    "severe_abdominal_pain": "Severe abdominal pain",
    "difficulty_breathing": "Difficulty breathing",
    "unconscious": "Loss of consciousness",
}

# Signs that warrant a visit this week, not an ambulance tonight.
AMBER_SIGNS = {
    "fever": "Fever",
    "swelling": "Swelling of face and hands",
    "severe_vomiting": "Persistent vomiting",
    "painful_urination": "Painful urination",
    "no_fetal_movement_mild": "Reduced fetal movement reported as mild",
}

MOTHER_MUAC_UNDERNUTRITION = 23.0
CHILD_MUAC_MODERATE = 12.5
CHILD_MUAC_SEVERE = 11.5
MDD_W_MINIMUM = 5      # of 10 food groups
MDD_CHILD_MINIMUM = 5  # of 8 food groups


class Reason:
    def __init__(self, code: str, severity: str, text: str, detail: Optional[str] = None):
        self.code = code
        self.severity = severity
        self.text = text
        self.detail = detail

    def to_dict(self):
        return {"code": self.code, "severity": self.severity,
                "text": self.text, "detail": self.detail}

    def __repr__(self):
        return "<Reason {} {}>".format(self.severity, self.code)


class Verdict:
    def __init__(self, level: str, reasons: List[Reason]):
        self.level = level
        self.reasons = reasons

    @property
    def codes(self) -> List[str]:
        return [r.code for r in self.reasons]

    def explain(self) -> str:
        """A one-line explanation, which is what a worker actually reads."""
        if not self.reasons:
            return "No danger signs reported."
        return " + ".join(r.text for r in self.reasons)

    def to_dict(self):
        return {"level": self.level,
                "reasons": [r.to_dict() for r in self.reasons],
                "explanation": self.explain()}


def _escalate(current: str, candidate: str) -> str:
    return candidate if _ORDER[candidate] > _ORDER[current] else current


def _number(value):
    """A measurement, or None -- never an exception.

    Payloads arrive from devices over a lossy link, and a stringified "11.0"
    used to raise TypeError deep inside a comparison, returning a 500 for that
    patient on every subsequent read.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(snapshot, patient=None) -> Verdict:
    """Classify a folded snapshot. Pure: no database, no clock, no I/O."""
    level = GREEN
    reasons: List[Reason] = []

    # --- danger signs ---------------------------------------------------
    for sign in snapshot.active_danger_signs:
        if sign in RED_SIGNS:
            level = _escalate(level, RED)
            reasons.append(Reason("sign." + sign, RED, RED_SIGNS[sign]))
        elif sign in AMBER_SIGNS:
            level = _escalate(level, AMBER)
            reasons.append(Reason("sign." + sign, AMBER, AMBER_SIGNS[sign]))

    # --- nutrition: mother ----------------------------------------------
    muac_mother = _number(snapshot.muac_mother)
    muac_child = _number(snapshot.muac_child)
    if muac_mother is not None and muac_mother < MOTHER_MUAC_UNDERNUTRITION:
        level = _escalate(level, AMBER)
        reasons.append(Reason(
            "muac.mother_low", AMBER,
            "Mother's MUAC below 23 cm",
            "{:.1f} cm — undernutrition in pregnancy".format(muac_mother)))

    # --- nutrition: child -----------------------------------------------
    if muac_child is not None:
        if muac_child < CHILD_MUAC_SEVERE:
            level = _escalate(level, RED)
            reasons.append(Reason(
                "muac.child_severe", RED,
                "Child MUAC below 11.5 cm — severe acute malnutrition",
                "Refer to CMAM"))
        elif muac_child < CHILD_MUAC_MODERATE:
            level = _escalate(level, AMBER)
            reasons.append(Reason(
                "muac.child_moderate", AMBER,
                "Child MUAC below 12.5 cm — moderate acute malnutrition",
                "{:.1f} cm".format(muac_child)))

    # --- dietary diversity ----------------------------------------------
    # One low reading is a bad week. Two in a row is a pattern worth a visit.
    minimum = (MDD_W_MINIMUM if snapshot.mdd_instrument == "mdd_w"
               else MDD_CHILD_MINIMUM)
    scores = [_number(s) for s in snapshot.mdd_history[-2:]]
    recent_low = [s for s in scores if s is not None and s < minimum]
    if len(recent_low) >= 2:
        level = _escalate(level, AMBER)
        reasons.append(Reason(
            "diet.persistently_low", AMBER,
            "Dietary diversity below the minimum on consecutive contacts",
            "Last scores: " + ", ".join(
                str(int(s)) for s in scores if s is not None)))

    # --- iron and folic acid --------------------------------------------
    if snapshot.ifa_adherent is False:
        level = _escalate(level, AMBER)
        reasons.append(Reason(
            "ifa.not_adherent", AMBER,
            "Not taking iron and folic acid",
            "Anaemia risk — resupply and counsel"))

    # --- silence is not safety -------------------------------------------
    if snapshot.consecutive_unreachable >= 3:
        level = _escalate(level, AMBER)
        reasons.append(Reason(
            "contact.unreachable", AMBER,
            "Unreachable on three consecutive attempts",
            "Needs a physical visit — do not treat silence as safety"))

    # --- access modifier ---------------------------------------------------
    # Distance does not create an emergency; it shortens how long one can safely
    # be left. So it escalates only CLINICAL ambers -- a symptom that could
    # deteriorate -- and never an adherence or diet flag. Escalating "not taking
    # iron tablets" to a night-time motorking because the road is poor would
    # burn the driver network's goodwill within a week, and in a region where
    # most CHPS catchments have poor roads it would escalate almost everything.
    if patient is not None and level == AMBER:
        minutes = getattr(patient, "minutes_to_facility", None) or 0
        road = getattr(patient, "road_condition", None)
        remote = minutes >= 90 or (minutes >= 45 and road == "poor")
        clinical = any(r.code.startswith("sign.") or r.code.startswith("muac.")
                       for r in reasons)
        if remote and clinical:
            level = RED
            reasons.append(Reason(
                "access.remote", RED,
                "Far from care on a poor road",
                "{} minutes away — a symptom that could worsen cannot wait a "
                "week at this distance".format(minutes)))
        elif remote:
            reasons.append(Reason(
                "access.slow", AMBER,
                "{} minutes from care".format(minutes),
                "Visit sooner than usual; reaching help takes longer here"))

    # --- an open RED stays RED -------------------------------------------
    if snapshot.red_open and level != RED:
        level = RED
        reasons.append(Reason(
            "emergency.open", RED,
            "Emergency still open",
            "A RED stays RED until a health worker records the outcome"))

    return Verdict(level, reasons)


# Reason codes are what the engine stores; these are what a person reads. Kept
# here so the SMS a CHO gets at 2am says "Bleeding" and not "sign.bleeding".
_EXTRA_LABELS = {
    "muac.mother_low": "Mother's MUAC below 23 cm",
    "muac.child_moderate": "Child MUAC below 12.5 cm",
    "muac.child_severe": "Child MUAC below 11.5 cm",
    "diet.persistently_low": "Diet low twice running",
    "ifa.not_adherent": "Not taking iron tablets",
    "contact.unreachable": "Unreachable three times",
    "access.remote": "Far from care",
    "emergency.open": "Emergency still open",
    "hotline.nurse_unreachable": "Could not reach a nurse",
    "call.hotline_unfinished": "Rang the hotline; we could not take her answers",
}


def label_for(code: str) -> str:
    if code.startswith("sign."):
        key = code[5:]
        return RED_SIGNS.get(key) or AMBER_SIGNS.get(key) or key.replace("_", " ")
    return _EXTRA_LABELS.get(code, code.replace(".", " ").replace("_", " "))


def labels_for(codes, limit: int = 2) -> str:
    readable = [label_for(c) for c in (codes or [])[:limit]]
    return ", ".join(readable)
