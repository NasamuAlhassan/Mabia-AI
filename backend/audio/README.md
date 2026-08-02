# Recorded prompts

Files here are served publicly at `/audio/<language>/<key>.wav` so that Africa's
Talking can fetch them during a call. Anything missing falls back to spoken
English, so the flow is always testable before the recordings exist.

Keys come from `app/prompts.py`. The set needed for one complete language:

    greet_consent  danger_bleeding  danger_severe_headache  danger_convulsions
    danger_fever   danger_reduced_fetal_movement  birth_plan  closing
    reschedule     weeks_1 … weeks_8  nurse_connecting  nurse_unavailable
    driver_request driver_accepted  driver_declined
    diet_<group>   for each food group in the instrument

Record at 16 kHz mono. Telephony is narrowband, so judge them on a real call,
not on laptop speakers.

Dagbani first and complete; the other three follow.
