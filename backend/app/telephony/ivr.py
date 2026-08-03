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
    """A clip for this line in this language, if one exists on disk.

    With no public base URL configured -- a fresh checkout, or the simulator on
    a laptop -- this falls back to a root-relative path rather than giving up.
    The old behaviour was to return nothing, so on a machine that had not been
    deployed yet every recording in the repository was invisible and the whole
    voice pipeline demoed as though it did not exist. Africa's Talking needs an
    absolute URL, but if no base URL is set there is no real call to serve.
    """
    # One source of truth for where clips live, shared with the pipeline that
    # writes them. Computing it separately here meant the two could disagree,
    # and meant a test could not redirect audio without editing the repository's
    # own recordings.
    from ..language.pipeline import AUDIO_ROOT
    root = AUDIO_ROOT / language
    for suffix in (".wav", ".mp3", ".ogg"):
        if (root / (key + suffix)).exists():
            return "{}/audio/{}/{}{}".format(
                base_url.rstrip("/"), language, key, suffix)
    return None


def say_or_play(db, base_url: str, language: str, key: Optional[str],
                text: str) -> str:
    """One utterance: her recorded clip if there is one, else English.

    <Say> is the provider's English text-to-speech voice. There is no Dagbani,
    Kusaal, Frafra or Gonja voice behind it. Handing it Dagbani orthography
    does not produce Dagbani -- it produces an English voice failing at Dagbani,
    which is less use to the woman on the line than plain English is. So the
    translation is what we RECORD and what we SHOW; English is what we SAY when
    no recording exists.

    That is why the Voice screen's coverage figure is the number that matters:
    every point of it converts one of these <Say> fallbacks into a <Play> she
    can actually understand.
    """
    if key:
        url = _audio_url(base_url or "", language, key)
        if url:
            return '<Play url="{}"/>'.format(escape(url, {'"': "&quot;"}))
    return "<Say>{}</Say>".format(escape(text))


def utterance(db, base_url: str, language: str, parts) -> str:
    """Several lines spoken back to back, each resolved on its own.

    Turns are frequently built from more than one catalogue line -- a danger
    question plus the "press 9 for a nurse" hint, a nutrition message plus the
    birth-plan question, advice plus a date plus a goodbye. Joining them into
    one string and passing it under a single key was silently destructive: if a
    clip existed for that key it was played and everything else in the string
    was thrown away. That is how "press 9 to speak to a nurse" came to be
    dropped from every call in every language that had audio -- including the
    languages we had just finished recording.

    Resolving each part separately means a clip covers the part it is a clip
    of, and the rest still gets said.
    """
    out = []
    for key, text in parts:
        if not text:
            continue
        out.append(say_or_play(db, base_url, language, key, text))
    return "".join(out) or "<Say>.</Say>"


def ask_parts(db, base_url, language, parts, callback_url) -> str:
    return (
        '<Response><GetDigits numDigits="1" timeout="{}" callbackUrl="{}">'
        "{}</GetDigits></Response>"
    ).format(DIGIT_TIMEOUT, escape(callback_url, {'"': "&quot;"}),
             utterance(db, base_url, language, parts))


def tell_parts(db, base_url, language, parts) -> str:
    return "<Response>{}</Response>".format(
        utterance(db, base_url, language, parts))


def speak(db, base_url: str, language: str, key: str, text: str) -> str:
    return say_or_play(db, base_url, language, key, text)


def ask(db, base_url: str, language: str, key: str, text: str,
        callback_url: str) -> str:
    return ask_parts(db, base_url, language, [(key, text)], callback_url)


def tell(db, base_url: str, language: str, key: str, text: str) -> str:
    body = speak(db, base_url, language, key, text)
    return "<Response>{}</Response>".format(body)


def dial(db, numbers: str, hold_text: str, base_url: str, language: str) -> str:
    return ('<Response>{}<Dial phoneNumbers="{}" record="false" '
            'sequential="true"/></Response>').format(
        speak(db, base_url, language, "nurse_connecting", hold_text),
        escape(numbers, {'"': "&quot;"}))


# ------------------------------------------------------- the transition


class Turn:
    """One step of the conversation: what to say, and what it meant."""

    def __init__(self, xml: str, finished: bool = False, note: str = ""):
        self.xml = xml
        self.finished = finished
        self.note = note


# Quickening is around 18-20 weeks in a first pregnancy. Asking before that
# whether the baby has stopped moving asks about something she has never felt,
# and a "yes" fires an emergency, an SMS to her health worker, a message to her
# family and a driver cascade. A midwife spots this before you finish the
# sentence.
QUICKENING_WEEK = 20

# A wrong key re-asks, but not without limit. Silence was already capped at two
# tries; a misdial was capped at nothing, so the call could be held open for as
# long as keys kept being pressed -- at her cost as much as ours.
MAX_MISDIALS = 3


def gestational_week(db, session: CallSession):
    """Her week of pregnancy, or None if we do not know."""
    if not session.patient_id:
        return None
    patient = db.get(Patient, session.patient_id)
    if patient is None or not patient.edd:
        return None
    remaining = (patient.edd - dt.date.today()).days
    return max(0, min(45, 40 - remaining // 7))


def danger_questions_for(db, session: CallSession):
    """The danger signs worth asking THIS woman at THIS point in her pregnancy."""
    week = gestational_week(db, session)
    if week is None:
        # Gestation unknown: ask everything rather than assume, but the fetal
        # movement question is the one that misfires, so it goes last.
        return list(DANGER_QUESTIONS)
    return [(key, text) for key, text in DANGER_QUESTIONS
            if not (key == "reduced_fetal_movement" and week < QUICKENING_WEEK)]


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
    # A woman who flashed the hotline is not on a routine antenatal contact.
    # She rang because something is wrong, and she was being answered with the
    # scheduled check-in greeting -- "is this a good time to talk?" -- where
    # pressing 2 ended her emergency call with "we will call you another time".
    # She was also never told about pressing 9, because the escape hint only
    # played after she had already pressed 1.
    if state == GREET and session.purpose == "hotline":
        if digit is None:
            session.no_input = (session.no_input or 0) + 1
            if session.no_input > 2:
                return _give_up(db, session, base_url, language, transcript)
            session.transcript = transcript
            db.flush()
            return Turn(ask_parts(db, base_url, language, [
                ("hotline_greet", prompts.line("hotline_greet")),
                ("hotline_menu", prompts.line("hotline_menu")),
            ], callback_url))

        remember("hotline_menu", digit)
        if digit == "1":
            # Straight into the danger questions. No consent step: she called us.
            session.state = DANGER
            session.cursor = 0
            asked = danger_questions_for(db, session)
            answers["asked_signs"] = [k for k, _ in asked]
            session.answers = answers
            session.transcript = transcript
            db.flush()
            key, text = asked[0]
            return Turn(ask_parts(db, base_url, language, [
                ("escape_hint", prompts.line("escape_hint")),
                ("danger_" + key, text),
            ], callback_url))

        misdials = answers.get("misdials", 0) + 1
        answers["misdials"] = misdials
        session.answers = answers
        session.transcript = transcript
        db.flush()
        if misdials > MAX_MISDIALS:
            return _give_up(db, session, base_url, language, transcript)
        return Turn(ask_parts(db, base_url, language, [
            ("not_understood", prompts.line("not_understood")),
            ("hotline_menu", prompts.line("hotline_menu")),
        ], callback_url))

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
                return Turn(tell(db, base_url, language, "no_answer",
                                 prompts.line("no_answer")),
                            finished=True, note="no_input")
            session.state = GREET
            session.transcript = transcript
            db.flush()
            text = "{} {}".format(prompts.line("greet"), prompts.line("consent"))
            return Turn(ask(db, base_url, language, "greet_consent", text, callback_url))
        if digit not in ("1", "2"):
            # A misdial re-asks, but not forever. Silence is capped at two
            # tries and a wrong key was not capped at all, so a handset with a
            # sticky keypad -- or a child playing with the phone -- held the
            # line open indefinitely at her cost and ours.
            misdials = answers.get("misdials", 0) + 1
            answers["misdials"] = misdials
            session.answers = answers
            session.transcript = transcript
            db.flush()
            if misdials > MAX_MISDIALS:
                return _give_up(db, session, base_url, language, transcript)
            return Turn(ask_parts(db, base_url, language, [
                ("not_understood", prompts.line("not_understood")),
                ("consent", prompts.line("consent")),
            ], callback_url))
        remember("consent", digit)
        if digit != "1":
            session.state = DONE
            session.outcome = "rescheduled"
            session.transcript = transcript
            db.flush()
            return Turn(tell(db, base_url, language, "reschedule",
                             prompts.line("reschedule")), finished=True,
                        note="rescheduled")
        session.state = DANGER
        session.cursor = 0
        # Pin the question set for the whole call: cursor indexes into it, and
        # a list that changed mid-call would ask the wrong question.
        asked = danger_questions_for(db, session)
        answers["asked_signs"] = [k for k, _ in asked]
        session.answers = answers
        session.transcript = transcript
        db.flush()
        key, text = asked[0]
        # She has agreed to talk, so now tell her how to reach a person. Said
        # here rather than in the greeting: it is only useful once she is in the
        # conversation, and it kept the greeting past the synthesis ceiling.
        return Turn(ask_parts(db, base_url, language, [
            ("escape_hint", prompts.line("escape_hint")),
            ("danger_" + key, text),
        ], callback_url))

    # --- danger signs ----------------------------------------------------
    if state == DANGER:
        pinned = answers.get("asked_signs") or [k for k, _ in DANGER_QUESTIONS]
        by_key = dict(DANGER_QUESTIONS)
        asked = [(k, by_key[k]) for k in pinned if k in by_key]
        if session.cursor >= len(asked):
            session.cursor = len(asked) - 1
        key, _ = asked[session.cursor]
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
            _, again = asked[session.cursor]
            return Turn(ask_parts(db, base_url, language, [
                ("not_understood", prompts.line("not_understood")),
                ("danger_" + key, again),
            ], callback_url))
        else:
            # Re-ask once before giving up on the question.
            tries = answers.setdefault("retries", {})
            if tries.get(key, 0) < 1:
                tries[key] = tries.get(key, 0) + 1
                session.answers = answers
                session.transcript = transcript
                db.flush()
                _, again = asked[session.cursor]
                return Turn(ask_parts(db, base_url, language, [
                    ("not_understood", prompts.line("not_understood")),
                    ("danger_" + key, again),
                ], callback_url))
            answers.setdefault("danger", {})[key] = None

        nxt = session.cursor + 1
        if nxt < len(asked):
            session.cursor = nxt
            session.answers = answers
            session.transcript = transcript
            db.flush()
            nkey, ntext = asked[nxt]
            return Turn(ask(db, base_url, language, "danger_" + nkey, ntext, callback_url))

        # Danger block finished. Diet next, if this contact carries it.
        if session.include_diet:
            session.state = DIET
            session.cursor = 0
            answers.setdefault("instrument", MDD_W)
            session.answers = answers
            session.transcript = transcript
            db.flush()
            qs = diet_questions_for(session)
            return Turn(ask(db, base_url, language, "diet_" + qs[0]["group"],
                            qs[0]["prompt"], callback_url))
        session.state = BIRTH_PLAN
        session.answers = answers
        session.transcript = transcript
        db.flush()
        bkey, btext = prompts.BIRTH_PLAN_QUESTION
        return Turn(ask(db, base_url, language, bkey, btext, callback_url))

    # --- dietary diversity ------------------------------------------------
    if state == DIET:
        qs = diet_questions_for(session)
        group = qs[session.cursor]["group"]
        remember("diet_" + group, digit)
        if digit not in ("1", "2"):
            misdials = answers.get("misdials", 0) + 1
            answers["misdials"] = misdials
            session.answers = answers
            session.transcript = transcript
            db.flush()
            if misdials > MAX_MISDIALS:
                return _give_up(db, session, base_url, language, transcript)
            return Turn(ask_parts(db, base_url, language, [
                ("not_understood", prompts.line("not_understood")),
                ("diet_" + group, qs[session.cursor]["prompt"]),
            ], callback_url))
        answers.setdefault("diet", {})[group] = (digit == "1")
        nxt = session.cursor + 1
        if nxt < len(qs):
            session.cursor = nxt
            session.answers = answers
            session.transcript = transcript
            db.flush()
            return Turn(ask(db, base_url, language, "diet_" + qs[nxt]["group"],
                            qs[nxt]["prompt"], callback_url))

        # All groups asked -- choose the single message she will actually hear.
        session.state = NUTRITION
        session.answers = answers
        session.transcript = transcript
        db.flush()
        advice, food_key = _nutrition_message(db, session)
        # Written into `answers`, which is what advance flushes. The helper used
        # to assign session.answers itself and advance then reassigned its own
        # local dict over the top, so both of these were silently dropped at
        # flush -- which meant `exclude` read None forever and she was given
        # word-for-word identical advice at every single contact. That is the
        # failure the no-repeat logic exists to prevent.
        answers["nutrition_message"] = " ".join(t for _, t in advice)
        answers["nutrition_food"] = food_key
        session.answers = answers
        session.state = BIRTH_PLAN
        db.flush()
        return Turn(ask_parts(db, base_url, language,
                              list(advice) + [prompts.BIRTH_PLAN_QUESTION],
                              callback_url))

    # --- birth preparedness ------------------------------------------------
    if state == BIRTH_PLAN:
        remember("birth_plan", digit)

        # The danger block refuses to read silence as an answer, and this branch
        # did exactly that: a dropped keypress on a bad line was recorded as
        # "she has made no birth plan", she was given the advice for it, and the
        # call ended. Silence and a wrong key both re-ask; only after that do we
        # record that we do not know.
        if digit not in ("1", "2"):
            tries = answers.get("birth_plan_tries", 0) + 1
            answers["birth_plan_tries"] = tries
            session.answers = answers
            session.transcript = transcript
            db.flush()
            if tries <= 2:
                bkey, btext = prompts.BIRTH_PLAN_QUESTION
                parts = [(bkey, btext)]
                if digit is not None:
                    parts.insert(0, ("not_understood",
                                     prompts.line("not_understood")))
                return Turn(ask_parts(db, base_url, language, parts,
                                      callback_url))
            answers["birth_plan_ready"] = None
        else:
            answers["birth_plan_ready"] = (digit == "1")
        session.answers = answers
        session.state = NEXT_VISIT
        session.transcript = transcript
        db.flush()
        # No advice claiming to know either way when she never answered.
        advice_key = ("birth_plan_yes" if answers.get("birth_plan_ready")
                      else "birth_plan_no"
                      if answers.get("birth_plan_ready") is False else None)
        weeks = _weeks_to_next_visit(db, session)
        weeks_key = prompts.weeks_key(weeks)

        # If she reported anything dangerous, she must not be sent away with
        # "we will text you the date". red_closing exists, is translated, and
        # was never once emitted: she was told to expect a message instead of
        # being told her health worker had been alerted and not to travel alone.
        reported = [k for k, v in (answers.get("danger") or {}).items() if v is True]
        closing_key = "red_closing" if reported else "closing"

        parts = ([(advice_key, prompts.line(advice_key))] if advice_key
                 else [])
        if not reported:
            parts += [("next_visit_prefix", prompts.line("next_visit_prefix")),
                      (weeks_key, prompts.line(weeks_key))]
        parts.append((closing_key, prompts.line(closing_key)))

        session.state = DONE
        db.flush()
        return Turn(tell_parts(db, base_url, language, parts),
                    finished=True, note="completed")

    # --- anything unexpected ------------------------------------------------
    session.state = DONE
    session.transcript = transcript
    db.flush()
    return Turn(tell(db, base_url, language, "closing", prompts.line("closing")),
                finished=True, note="completed")


def _give_up(db, session, base_url, language, transcript):
    """End a call that is not getting anywhere, and say why in the record."""
    session.state = DONE
    session.outcome = "no_input"
    session.transcript = transcript
    db.flush()
    return Turn(tell(db, base_url, language, "no_answer",
                     prompts.line("no_answer")),
                finished=True, note="too many misdials")


def _nutrition_message(db: Session, session: CallSession):
    """The advice as ([(key, text)], food_key). Writes nothing itself.

    This used to return a bare string, which was then passed into the turn with
    no key at all. The catalogue holds a food_<key> line and a recording for
    every food in the table -- thirty-four of them, the entire output of the
    nutrition engine -- and not one could ever be played, because nothing told
    the utterance layer which line it was looking at.
    """
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
        return [], None

    # The anaemia tip is a separate catalogue line with its own recording, so
    # it stays a separate part rather than being glued onto the advice.
    parts = [("food_" + rec.food["key"] if rec.food else None, rec.message)]
    if rec.anaemia_tip:
        parts.append((prompts.anaemia_tip_key(rec.anaemia_tip), rec.anaemia_tip))
    return parts, (rec.food["key"] if rec.food else None)


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
