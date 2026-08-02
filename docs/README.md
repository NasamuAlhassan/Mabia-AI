# Documents

- **`Mabia_AI_System_Architecture.docx`** — the submission document: problem
  statement, system users, the eleven-phase flow, the nutrition engine, the
  language pipeline, data protection, build status, impact measurement,
  verification and team.

  Seventeen sections. The two worth reading first are **§13 Build Status**,
  which distinguishes what is built from what is blocked and what is not
  possible, and **§15 Verification**, which lists what the tests actually
  assert. Both are written so a reader can check them against the code rather
  than take them on trust.

The code is the authority on behaviour; where the two disagree, the code is
right and the document needs an edit.

## Quick map from document to code

| Document section | Where it lives |
|---|---|
| §5 Phase 2–3, offline capture and sync | `backend/app/events.py`, `frontend/src/db.js` |
| §5 Phase 4, proactive outreach | `backend/app/telephony/ivr.py`, `services.py` (`build_contact_schedule`) |
| §5 Phase 6, risk engine | `backend/app/engines/risk.py` |
| §5 Phase 7, SMS push and USSD pull | `backend/app/api/telephony.py` |
| §5 Phase 8, transport | `backend/app/services.py` (`offer_next_driver`) |
| §5 Phase 11, hotline and nurse cascade | `backend/app/services.py` (`nurse_target`, `terminal_fallback`) |
| §8 Local-food nutrition intelligence | `backend/app/engines/nutrition.py`, `backend/app/data/foods.py` |
| §12 Data protection | consent at enrolment; no automated location tracking; see `models.py` |
| §13 Build status | the table is checkable against this repository; if the two disagree, the code is right |
| §15 Verification | `backend/tests/test_mabia.py` and `backend/tests/test_regressions.py` |
