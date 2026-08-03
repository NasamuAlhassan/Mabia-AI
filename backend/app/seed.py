"""Demo data: a CHPS zone you can actually walk a judge through.

Seeded once, only into an empty database. The caseload is built so that opening
the worklist shows the whole argument in one screen: a RED that came from a
phone call, an AMBER that came from a MUAC tape, and a GREEN whose diet was fine.
"""
import datetime as dt

from sqlalchemy.orm import Session

from . import events as ev
from . import services
from .models import Driver, Facility, NurseShift, Patient, User
from .security import hash_pin

DEFAULT_PIN = "1234"


def seed(db: Session) -> None:
    if db.query(User).count() > 0:
        return

    today = dt.date.today()

    kpale = Facility(name="Kpale CHPS Compound", community="Kpale",
                     region="Northern", phone="+233200000010")
    tamale = Facility(name="Tamale West Hospital", community="Tamale",
                      region="Northern", phone="+233200000011")
    db.add_all([kpale, tamale])
    from .language import pipeline as language_pipeline
    for lang in language_pipeline.ALL_LANGUAGES:
        language_pipeline.sync_catalogue(db, lang)

    db.flush()

    cho = User(name="Fatima Abdulai", phone="+233200000001",
               pin_hash=hash_pin(DEFAULT_PIN), role="cho", community="Kpale",
               facility_id=kpale.id, language="dagbani")
    nutritionist = User(name="Dawuda Mardia", phone="+233200000002",
                        pin_hash=hash_pin(DEFAULT_PIN), role="nutrition_officer",
                        community="Kpale", facility_id=kpale.id)
    nurse_one = User(name="Sister Ayisha", phone="+233200000003",
                     pin_hash=hash_pin(DEFAULT_PIN), role="nurse",
                     community="Kpale", facility_id=kpale.id)
    nurse_two = User(name="Sister Mariama", phone="+233200000004",
                     pin_hash=hash_pin(DEFAULT_PIN), role="nurse",
                     community="Tamale", facility_id=tamale.id)
    db.add_all([cho, nutritionist, nurse_one, nurse_two])
    db.flush()

    db.add_all([
        NurseShift(user_id=nurse_one.id, facility_id=kpale.id, on_call=True,
                   position=1),
        NurseShift(user_id=nurse_two.id, facility_id=tamale.id, on_call=True,
                   position=2),
    ])

    db.add_all([
        Driver(name="Iddrisu Mohammed", phone="+233200000021", community="Kpale",
               vehicle_type="motorking", accepted_count=7, offered_count=8),
        Driver(name="Alhassan Yakubu", phone="+233200000022", community="Kpale",
               vehicle_type="car", accepted_count=3, offered_count=7),
        Driver(name="Salifu Braimah", phone="+233200000023", community="Sagnarigu",
               vehicle_type="motorbike", accepted_count=2, offered_count=3),
    ])
    db.flush()

    people = [
        # (name, phone, community, weeks pregnant, affordability, taboos)
        ("Amina Fuseini", "+233240000001", "Kpale", 32, "low", ["eggs"]),
        ("Zeinab Mahama", "+233240000002", "Kpale", 24, "low", []),
        ("Hawa Sulemana", "+233240000003", "Kpale", 36, "medium", []),
        ("Memuna Iddris", "+233240000004", "Sagnarigu", 12, "low", []),
        ("Rahma Osman", "+233240000005", "Kpale", 28, "low", ["goat"]),
    ]

    created = []
    for name, phone, community, weeks, affordability, taboos in people:
        edd = today + dt.timedelta(weeks=(40 - weeks))
        patient = Patient(
            name=name, phone=phone, secondary_phone="+233240000099",
            language="dagbani", community=community, region="Northern",
            lmp=edd - dt.timedelta(days=280), edd=edd,
            affordability=affordability, taboos=taboos, consent=True,
            consent_at=dt.datetime.utcnow(), assigned_cho_id=cho.id,
            facility_id=kpale.id)
        db.add(patient)
        db.flush()
        ev.append(db, patient_id=patient.id, actor_id=cho.id,
                  event_type=ev.ENROLMENT,
                  payload={"community": community, "weeks": weeks})
        ev.append(db, patient_id=patient.id, actor_id=cho.id,
                  event_type=ev.CONSENT_GIVEN, payload={"scope": ["scheduled_calls"]})
        services.build_contact_schedule(db, patient)
        created.append(patient)

    amina, zeinab, hawa, memuna, rahma = created
    day = dt.datetime.utcnow()

    # Amina: a RED that arrived by phone, not by visit. This is the whole point
    # of proactive outreach -- nobody would have known.
    ev.append(db, patient_id=amina.id, actor_id="system",
              event_type=ev.DANGER_SIGNS,
              occurred_at=day - dt.timedelta(hours=3),
              payload={"signs": ["bleeding"], "denied": ["fever", "convulsions"],
                       "source": "ivr"})
    ev.append(db, patient_id=amina.id, actor_id="system",
              event_type=ev.CALL_COMPLETED,
              occurred_at=day - dt.timedelta(hours=3),
              payload={"outcome": "completed"})

    # Zeinab: two low dietary scores in a row -- a pattern, not a bad week.
    for offset, score in ((14, 3), (2, 3)):
        ev.append(db, patient_id=zeinab.id, actor_id="system",
                  event_type=ev.DIET_RECALL,
                  occurred_at=day - dt.timedelta(days=offset),
                  payload={"instrument": "mdd_w", "score": score, "total": 10,
                           "present": ["grains", "other_veg", "nuts_seeds"],
                           "missing": ["pulses", "dairy", "flesh", "eggs",
                                       "dark_leafy", "vita_fruit_veg",
                                       "other_fruit"]})
    ev.append(db, patient_id=zeinab.id, actor_id=cho.id, event_type=ev.IFA,
              occurred_at=day - dt.timedelta(days=2), payload={"adherent": False})

    # Hawa: undernourished on the tape, which the phone would never have caught.
    ev.append(db, patient_id=hawa.id, actor_id=cho.id, event_type=ev.MUAC,
              occurred_at=day - dt.timedelta(days=1),
              payload={"subject": "mother", "value_cm": 21.4})

    # Memuna: a good contact. Green exists so the worklist is not all alarm.
    ev.append(db, patient_id=memuna.id, actor_id="system",
              event_type=ev.DIET_RECALL, occurred_at=day - dt.timedelta(days=3),
              payload={"instrument": "mdd_w", "score": 7, "total": 10,
                       "present": ["grains", "pulses", "nuts_seeds", "flesh",
                                   "dark_leafy", "other_veg", "other_fruit"],
                       "missing": ["dairy", "eggs", "vita_fruit_veg"]})
    ev.append(db, patient_id=memuna.id, actor_id="system",
              event_type=ev.CALL_COMPLETED,
              occurred_at=day - dt.timedelta(days=3),
              payload={"outcome": "completed"})

    # Rahma: silence. Three misses is not safety -- it is a reason to walk there.
    for offset in (5, 3, 1):
        ev.append(db, patient_id=rahma.id, actor_id="system",
                  event_type=ev.CALL_ATTEMPTED,
                  occurred_at=day - dt.timedelta(days=offset),
                  payload={"outcome": "unreachable"})

    # Amina's circle is complete; the others are deliberately partial, because
    # a demo where every record is perfect teaches a judge nothing about what
    # the product does when it is not.
    from .models import CareCircleMember
    db.add_all([
        CareCircleMember(patient_id=amina.id, role="decision_maker",
                         name="Mahamadu Fuseini", phone="+233240000101",
                         detail="Husband", confirmed=True),
        CareCircleMember(patient_id=amina.id, role="driver",
                         name="Iddrisu Mohammed", phone="+233200000021",
                         detail="Motorking", confirmed=True),
        CareCircleMember(patient_id=amina.id, role="payer",
                         name="NHIS", detail="NHIS 1234567890", confirmed=True),
        CareCircleMember(patient_id=amina.id, role="emergency",
                         name="Salamatu Fuseini", phone="+233240000102",
                         detail="Sister", confirmed=True),
        CareCircleMember(patient_id=zeinab.id, role="decision_maker",
                         name="Abu Mahama", phone="+233240000103",
                         detail="Husband", confirmed=False),
        CareCircleMember(patient_id=hawa.id, role="emergency",
                         name="Fati Sulemana", phone="+233240000104",
                         detail="Mother", confirmed=True),
    ])
    db.flush()

    for patient in created:
        ev.refresh_state(db, patient.id)

    from .models import PatientState
    amina_state = db.get(PatientState, amina.id)
    if amina_state and amina_state.risk_level == "red":
        services.raise_emergency(db, amina, amina_state.reason_codes or [],
                                 source="ivr")

    db.flush()
