"""The IVR state machine.

Nothing runs "inside" a call. Every keypress is a fresh HTTP request from
Africa's Talking carrying the same sessionId, so the conversation lives in the
database and this module is a pure transition function over it.

Two constraints shape everything here:

* **Answer in under two seconds.** Africa's Talking will drop or stall the call
  otherwise. So the per-keypress path does nothing expensive: it records an
  answer and returns the next prompt. Risk classification, event folding and
  alerting all happen once, at the end of the call, off the critical path.

* **One digit at a time.** Never ask for multi-digit input from someone who may
  be using a keypad for the first time, in labour, at night.

Press 9 reaches a nurse from any state. That escape hatch is unconditional and
does not depend on the system detecting its own failure.
"""
import copy
import datetime as dt
from typing import Optional, Tuple
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from .. import events as ev
from .. import prompts
from ..engines.nutrition import MDD_W, Recall, recommend
from ..models import CallSession, Patient
from ..prompts import DANGER_QUESTIONS

# Generous: a first-time keypad user, on a bad line, is slow.
DIGIT_TIMEOUT = 10
NURSE_KEY = "9"

GREET = "greet"
DANGER = "danger"
DIET = "diet"
NUTRITION = "nutrition"
BIRTH_PLAN = "birth_plan"
NEXT_VISIT = "next_visit"
NURSE = "nurse"
DONE = "done"


# ----------------------------------------------------------------- XML


def _audio_url(base_url: str, language: str, key: str) -> Optional[str]:
    """A recorded clip if we have one, otherwise None and we fall back to speech."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "audio" / language
    for suffix in (".wav", ".mp3"):
        if (root / (key + suffix)).exists():
            return "{}/audio/{}/{}{}".format(base_url.rstrip("/"), language, key, suffix)
    return None


def speak(base_url: str, language: str, key: str, text: str) -> str:
    url = _audio_url(base_url, language, key) if base_url else None
    if url:
        return '<Play url="{}"/>'.format(escape(url, {'"': "&quot;"}))
    return "<Say>{}</Say>".format(escape(text))


def ask(base_url: str, language: str, key: str, text: str, callback_url: str) -> str:
    inner = speak(base_url, language, key, text)
    return (
        '<Response><GetDigits numDigits="1" timeout="{}" callbackUrl="{}">'
        "{}</GetDigits></Response>"
    ).format(DIGIT_TIMEOUT, escape(callback_url, {'"': "&quot;"}), inner)


def tell(base_url: str, language: str, key: str, text: str, hangup: bool = True) -> str:
    body = speak(base_url, language, key, text)
    return "<Response>{}</Response>".format(body)


def dial(numbers: str, hold_text: str, base_url: str, language: str) -> str:
    return ('<Response>{}<Dial phoneNumbers="{}" record="false" '
            'sequential="true"/></Response>').format(
        speak(base_url, language, "nurse_connecting", hold_text),
        escape(numbers, {'"': "&quot;"}))


# ------------------------------------------------------- the transition


class Turn:
    """One step of the conversation: what to say, and what it meant."""

    def __init__(self, xml: str, finished: bool = False, note: str = ""):
        self.xml = xml
        self.finished = finished
        self.note = note


def diet_questions_for(session: CallSession):
    from ..engines.nutrition import questions
    return questions(session.answers.get("instrument", MDD_W))


def advance(db: Session, session: CallSession, digit: Optional[str],
            base_url: str, callback_url: str) -> Turn:
    """Move the call on by one keypress. Cheap by construction."""
    language = session.language or "english"
    # Deep copy, not shallow: a shallow copy shares the nested answer dicts with
    # the value SQLAlchemy committed, so mutating them changes both, no net
    # difference is seen at flush time, and the write is silently dropped. That
    # bug cost every danger-sign answer after the first one.
    answers = copy.deepcopy(session.answers or {})
    transcript = copy.deepcopy(session.transcript or [])

    def remember(prompt_key, pressed=None):
        transcript.append({"prompt": prompt_key, "pressed": pressed,
                           "at": dt.datetime.utcnow().isoformat()})

    # The unconditional escape hatch, available from every state.
    if digit == NURSE_KEY and session.purpose in ("outreach", "hotline"):
        session.state = NURSE
        session.escalated_to_nurse = True
        session.answers = answers
        session.transcript = transcript
        db.flush()
        return Turn("", finished=False, note="nurse")

    state = session.state or GREET

    # --- greeting and consent -------------------------------------------
    if state == GREET:
        if digit is None:
            # She may simply be listening, or the line may be bad, or she may
            # never have used a keypad. Ask twice, then stop -- an unanswered
            # call is a fact worth recording, not a loop to sit in.
            session.no_input = (session.no_input or 0) + 1
            if session.no_input > 2:
                session.state = DONE
                session.outcome = "no_input"
                session.transcript = transcript
                db.flush()
                return Turn(tell(base_url, language, "no_answer",
                                 prompts.line("no_answer")),
                            finished=True, note="no_input")
            session.state = GREET
            session.transcript = transcript
            db.flush()
            text = "{} {} {}".format(prompts.line("greet"), prompts.line("consent"),
                                     prompts.line("escape_hint"))
            return Turn(ask(base_url, language, "greet_consent", text, callback_url))
        if digit not in ("1", "2"):
            session.transcript = transcript
            db.flush()
            return Turn(ask(base_url, language, "greet_consent",
                            prompts.line("not_understood") + " " +
                            prompts.line("consent"), callback_url))
        remember("consent", digit)
        if digit != "1":
            session.state = DONE
            session.outcome = "rescheduled"
            session.transcript = transcript
            db.flush()
            return Turn(tell(base_url, language, "reschedule",
                             prompts.line("reschedule")), finished=True,
                        note="rescheduled")
        session.state = DANGER
        session.cursor = 0
        session.transcript = transcript
        db.flush()
        key, text = DANGER_QUESTIONS[0]
        return Turn(ask(base_url, language, "danger_" + key, text, callback_url))

    # --- danger signs ----------------------------------------------------
    if state == DANGER:
        key, _ = DANGER_QUESTIONS[session.cursor]
        remember("danger_" + key, digit)

        # Three states, not two. Africa's Talking sends an empty dtmfDigits on
        # timeout, and treating that as "no" would record a woman who is too
        # weak, confused or unfamiliar with a keypad to press anything as having
        # DENIED bleeding. In a product whose whole claim is that silence is not
        # safety, that would be the worst possible bug to ship.
        if digit == "1":
            answers.setdefault("danger", {})[key] = True
        elif digit == "2":
            answers.setdefault("danger", {})[key] = False
        elif digit is not None:
            # A misdial, a * or a #. Never record a stray key as a denial --
            # denials clear previously affirmed signs.
            session.transcript = transcript
            db.flush()
            _, again = DANGER_QUESTIONS[session.cursor]
            return Turn(ask(base_url, language, "danger_" + key,
                            prompts.line("not_understood") + " " + again,
                            callback_url))
        else:
            # Re-ask once before giving up on the question.
            tries = answers.setdefault("retries", {})
            if tries.get(key, 0) < 1:
                tries[key] = tries.get(key, 0) + 1
                session.answers = answers
                session.transcript = transcript
                db.flush()
                _, again = DANGER_QUESTIONS[session.cursor]
                return Turn(ask(base_url, language, "danger_" + key,
                                prompts.line("not_understood") + " " + again,
                                callback_url))
            answers.setdefault("danger", {})[key] = None

        nxt = session.cursor + 1
        if nxt < len(DANGER_QUESTIONS):
            session.cursor = nxt
            session.answers = answers
            session.transcript = transcript
            db.flush()
            nkey, ntext = DANGER_QUESTIONS[nxt]
            return Turn(ask(base_url, language, "danger_" + nkey, ntext, callback_url))

        # Danger block finished. Diet next, if this contact carries it.
        if session.include_diet:
            session.state = DIET
            session.cursor = 0
            answers.setdefault("instrument", MDD_W)
            session.answers = answers
            session.transcript = transcript
            db.flush()
            qs = diet_questions_for(session)
            return Turn(ask(base_url, language, "diet_" + qs[0]["group"],
                            qs[0]["prompt"], callback_url))
        session.state = BIRTH_PLAN
        session.answers = answers
        session.transcript = transcript
        db.flush()
        bkey, btext = prompts.BIRTH_PLAN_QUESTION
        return Turn(ask(base_url, language, bkey, btext, callback_url))

    # --- dietary diversity ------------------------------------------------
    if state == DIET:
        qs = diet_questions_for(session)
        group = qs[session.cursor]["group"]
        remember("diet_" + group, digit)
        if digit not in ("1", "2"):
            session.transcript = transcript
            db.flush()
            return Turn(ask(base_url, language, "diet_" + group,
                            prompts.line("not_understood") + " " +
                            qs[session.cursor]["prompt"], callback_url))
        answers.setdefault("diet", {})[group] = (digit == "1")
        nxt = session.cursor + 1
        if nxt < len(qs):
            session.cursor = nxt
            session.answers = answers
            session.transcript = transcript
            db.flush()
            return Turn(ask(base_url, language, "diet_" + qs[nxt]["group"],
                            qs[nxt]["prompt"], callback_url))

        # All groups asked -- choose the single message she will actually hear.
        session.state = NUTRITION
        session.answers = answers
        session.transcript = transcript
        db.flush()
        message = _nutrition_message(db, session)
        answers["nutrition_message"] = message
        session.answers = answers
        session.state = BIRTH_PLAN
        db.flush()
        bkey, btext = prompts.BIRTH_PLAN_QUESTION
        combined = "{} {}".format(message, btext)
        return Turn(ask(base_url, language, "nutrition_then_plan", combined,
                        callback_url))

    # --- birth preparedness ------------------------------------------------
    if state == BIRTH_PLAN:
        remember("birth_plan", digit)
        answers["birth_plan_ready"] = (digit == "1")
        session.answers = answers
        session.state = NEXT_VISIT
        session.transcript = transcript
        db.flush()
        advice = prompts.line("birth_plan_yes" if digit == "1" else "birth_plan_no")
        weeks = _weeks_to_next_visit(db, session)
        closing = "{} {} {} {}".format(
            advice, prompts.line("next_visit_prefix"),
            prompts.line(prompts.weeks_key(weeks)), prompts.line("closing"))
        session.state = DONE
        db.flush()
        return Turn(tell(base_url, language, "closing", closing), finished=True,
                    note="completed")

    # --- anything unexpected ------------------------------------------------
    session.state = DONE
    session.transcript = transcript
    db.flush()
    return Turn(tell(base_url, language, "closing", prompts.line("closing")),
                finished=True, note="completed")


def _nutrition_message(db: Session, session: CallSession) -> str:
    patient = db.get(Patient, session.patient_id) if session.patient_id else None
    diet = (session.answers or {}).get("diet", {})
    present = [group for group, eaten in diet.items() if eaten]
    instrument = (session.answers or {}).get("instrument", MDD_W)
    recall = Recall(instrument, present)

    anaemia = False
    if patient is not None:
        from ..models import PatientState
        state = db.get(PatientState, patient.id)
        anaemia = bool(state and state.ifa_adherent is False)

    # Do not repeat last contact's advice. She stops hearing a sentence she
    # has heard before, and `exclude` existed for this and was never passed.
    previous = []
    if patient is not None:
        from ..models import Event
        last = (db.query(Event)
                  .filter(Event.patient_id == patient.id,
                          Event.event_type == ev.DIET_RECALL)
                  .order_by(Event.occurred_at.desc()).first())
        if last and (last.payload or {}).get("food_key"):
            previous = [last.payload["food_key"]]

    rec = recommend(
        recall,
        region=(patient.region if patient else "Northern"),
        month=dt.date.today().month,
        affordability=(patient.affordability if patient else "low"),
        taboos=(patient.taboos if patient else []) or [],
        anaemia_focus=anaemia,
        exclude=previous,
    )
    if rec is None:
        return ""
    if rec.food:
        session.answers = dict(session.answers or {},
                               nutrition_food=rec.food["key"])
    text = rec.message
    if rec.anaemia_tip:
        text = "{} {}".format(text, rec.anaemia_tip)
    return text


def _weeks_to_next_visit(db: Session, session: CallSession) -> int:
    from ..models import Contact
    if not session.patient_id:
        return 4
    today = dt.date.today()
    nxt = (db.query(Contact)
             .filter(Contact.patient_id == session.patient_id,
                     Contact.status == "pending",
                     Contact.due_date > today)
             .order_by(Contact.due_date.asc())
             .first())
    if not nxt:
        return 4
    return max(1, min(8, (nxt.due_date - today).days // 7 or 1))


# ------------------------------------------------------- end of call


def finalise(db: Session, session: CallSession) -> Tuple[str, list]:
    """Fold the call into the log. Runs after the call, once, never during it.

    Guarded because a stray extra keypress -- a judge double-tapping, or a
    provider retrying the last webhook -- used to re-run this and write the
    whole call into the log a second time. Two identical diet recalls then read
    as "below the minimum on CONSECUTIVE contacts" and manufactured a clinical
    finding out of one call.
    """
    if session.finalised:
        return ("green", [])
    session.finalised = True
    answers = session.answers or {}
    danger = answers.get("danger", {})
    affirmed = [k for k, v in danger.items() if v is True]
    denied = [k for k, v in danger.items() if v is False]
    unanswered = [k for k, v in danger.items() if v is None]

    if session.patient_id and (affirmed or denied or unanswered):
        ev.append(db, patient_id=session.patient_id, actor_id="system",
                  event_type=ev.DANGER_SIGNS,
                  payload={"signs": affirmed, "denied": denied,
                           "unanswered": unanswered,
                           "source": "ivr", "session": session.id})

    diet = answers.get("diet")
    if session.patient_id and diet:
        instrument = answers.get("instrument", MDD_W)
        recall = Recall(instrument, [g for g, eaten in diet.items() if eaten])
        ev.append(db, patient_id=session.patient_id, actor_id="system",
                  event_type=ev.DIET_RECALL,
                  payload={"instrument": instrument, "score": recall.score,
                           "total": recall.total, "missing": recall.missing,
                           "present": recall.present,
                           "food_key": answers.get("nutrition_food"),
                           "message": answers.get("nutrition_message")})

    if session.patient_id:
        ev.append(db, patient_id=session.patient_id, actor_id="system",
                  event_type=ev.CALL_COMPLETED,
                  payload={"session": session.id, "outcome": session.outcome,
                           "birth_plan_ready": answers.get("birth_plan_ready")})
        state = ev.refresh_state(db, session.patient_id)
        return state.risk_level, state.reason_codes or []
    return "green", []
