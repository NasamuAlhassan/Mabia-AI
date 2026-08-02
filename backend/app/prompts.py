"""The call script.

Every line is short on purpose. On a poor rural line a thirty-second prompt
loses the listener halfway through, so nothing here runs past about eight
seconds when spoken.

Nothing dynamic is ever spoken. There is no text-to-speech for Dagbani, Kusaal,
Frafra or Gonja, so a date cannot be synthesised -- which is why the closing line
says "in three weeks" from a fixed set of clips rather than "on 14 September",
and the exact date follows by SMS. When the team's own TTS models land, that
constraint lifts and this file is what they render.

Audio files, when recorded, live at backend/audio/<language>/<key>.wav and are
served publicly so Africa's Talking can fetch them. Where a clip is missing the
engine falls back to spoken English, so the flow is always testable.
"""

LANGUAGES = ["dagbani", "kusaal", "frafra", "gonja", "english"]

# --- danger signs asked on every call ---------------------------------------
# Five questions, single keypress each. These are the ones where waiting for a
# second signal costs a life.
DANGER_QUESTIONS = [
    ("bleeding", "Are you bleeding from the birth canal? Press 1 for yes, 2 for no."),
    ("severe_headache", "Do you have a bad headache, or blurred vision? Press 1 for yes, 2 for no."),
    ("convulsions", "Have you had fits or convulsions? Press 1 for yes, 2 for no."),
    ("fever", "Do you have a fever? Press 1 for yes, 2 for no."),
    ("reduced_fetal_movement", "Has the baby stopped moving, or moved much less? Press 1 for yes, 2 for no."),
]

BIRTH_PLAN_QUESTION = (
    "birth_plan",
    "Have you set aside money, arranged transport, and found someone to give "
    "blood? Press 1 for yes, 2 for not yet.")

SCRIPT = {
    "greet": "Hello. This is Mabia, calling about your pregnancy care.",
    "consent": "Is this a good time to talk? Press 1 for yes, 2 for later.",
    "reschedule": "That is fine. We will call you another time. Goodbye.",
    "escape_hint": "At any time, press 9 to speak to a nurse.",
    "diet_intro": "Now a few questions about what you ate yesterday.",
    "birth_plan_yes": "That is good. Keep the money and the transport ready.",
    "birth_plan_no": "Please arrange money, transport and a blood donor before "
                     "the birth. Your health worker will help you.",
    "next_visit_prefix": "Your next visit is in",
    "weeks_1": "one week.", "weeks_2": "two weeks.", "weeks_3": "three weeks.",
    "weeks_4": "four weeks.", "weeks_5": "five weeks.", "weeks_6": "six weeks.",
    "weeks_7": "seven weeks.", "weeks_8": "eight weeks.",
    "closing": "Thank you. We will send the date by message. Goodbye.",
    "red_closing": "Thank you. Your health worker is being told now, and someone "
                   "will call you. Please do not travel alone. Goodbye.",
    "nurse_connecting": "Please hold. We are connecting you to a nurse.",
    "nurse_unavailable": "We could not reach a nurse just now. Your health worker "
                         "has been told, and someone will call you back. Goodbye.",
    "hotline_greet": "Hello. This is Mabia. We are calling you back so this call "
                     "costs you nothing.",
    "hotline_menu": "Press 1 if this is an emergency. Press 9 to speak to a nurse.",
    "driver_request": "Urgent. A woman needs transport to the health centre. "
                      "Press 1 to accept, 2 if you cannot come.",
    "driver_accepted": "Thank you. Please go now. The health worker will call you.",
    "driver_declined": "Thank you. We will ask another driver.",
    "not_understood": "Sorry, I did not get that.",
    "no_answer": "We could not hear any answer. Your health worker will visit "
                 "you. Goodbye.",
}


def weeks_key(weeks: int) -> str:
    return "weeks_{}".format(max(1, min(8, int(weeks))))


def line(key: str) -> str:
    return SCRIPT.get(key, "")
