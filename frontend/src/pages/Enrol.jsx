import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, post } from '../api'
import { outbox, uuid7 } from '../db'
import CareCircle from '../components/CareCircle'

// Enrolment happens in a compound, standing up, often with no signal.
//
// So: the id is generated here on the device, because the server de-duplicates
// on it and a retry must enrol one woman rather than two. Consent is its own
// step with three separate toggles, because it is three separate consents and
// because a 22px checkbox squeezed by a global input rule is not how you record
// permission to store someone's health data. And "enrol another" keeps the
// community and language, because she enrols six women in one compound and
// retyping "Kpale" six times is how forms get abandoned.

const TABOOS = [
  ['eggs', 'Eggs'], ['goat', 'Goat meat'], ['guinea_fowl', 'Guinea fowl'],
  ['fresh_fish', 'Fresh fish'], ['milk_fresh', 'Fresh milk'],
]

const STEPS = ['Who she is', 'Where she is', 'Her household', 'Consent']

const BLANK = {
  name: '', phone: '', secondary_name: '', secondary_phone: '',
  language: 'dagbani', community: 'Kpale', region: 'Northern', edd: '',
  minutes_to_facility: '', road_condition: 'fair', affordability: 'low',
}

export default function Enrol() {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [f, setF] = useState(BLANK)
  const [taboos, setTaboos] = useState([])
  const [consents, setConsents] = useState({ calls: false, record: false, contact: false })
  const [flash, setFlash] = useState(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState({})

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const allConsented = consents.calls && consents.record

  function validate() {
    const next = {}
    if (!f.name.trim()) next.name = 'Her name is needed.'
    // Accept it however she writes it -- 024 000 0001, 024-000-0001,
    // +233 24 000 0001. The server settles on one form; she should not have to.
    if (!/^\+?\d{9,15}$/.test(f.phone.replace(/[\s()\-.]/g, ''))) {
      next.phone = 'A phone number like 024 000 0001.'
    }
    if (!f.community.trim()) next.community = 'Which community?'
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function submit() {
    if (!validate()) { setStep(0); return }
    setBusy(true); setFlash(null)
    const event_id = uuid7()
    const body = {
      ...f, taboos, consent: true, event_id,
      edd: f.edd || null,
      minutes_to_facility: f.minutes_to_facility
        ? parseInt(f.minutes_to_facility, 10) : null,
    }
    try {
      const created = await post('/api/patients', body)
      setFlash({ ok: true, id: created.id, name: created.name })
      setStep(4)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        await outbox.add({
          event_id, event_type: 'enrolment', payload: body,
          occurred_at: new Date().toISOString(),
        })
        setFlash({ queued: true, name: f.name })
        setStep(4)
      } else {
        setFlash({ bad: true, text: err.message })
      }
    } finally { setBusy(false) }
  }

  function another() {
    // Keep where we are and who we speak to; clear the person.
    setF({ ...BLANK, community: f.community, region: f.region,
           language: f.language, road_condition: f.road_condition,
           minutes_to_facility: f.minutes_to_facility })
    setTaboos([]); setConsents({ calls: false, record: false, contact: false })
    setFlash(null); setErrors({}); setStep(0)
  }

  if (step === 4) {
    return (
      <div className="card">
        <h1>{flash?.queued ? 'Saved on this phone' : 'Enrolled'}</h1>
        <p style={{ fontSize: '1.1rem' }}>
          <strong>{flash?.name}</strong>{' '}
          {flash?.queued
            ? 'is saved here and will sync by herself when you have a bar. '
              + 'Her call schedule is created when she syncs.'
            : 'is enrolled. Her eight antenatal calls are scheduled from her due date.'}
        </p>
        {/* The care circle asked for here, while the CHO is still sitting in
            the compound with the family in front of her. Asked later, from an
            office, it is a phone call to someone who does not know why she is
            asking -- which is why it sat empty for most households. */}
        {flash?.id && !flash?.queued && (
          <>
            <p className="muted tiny" style={{ marginTop: 16 }}>
              Before you leave the compound: who decides, who drives, who pays,
              who to ring. This is the difference between a referral that
              happens and one that does not.
            </p>
            <CareCircle patientId={flash.id} />
          </>
        )}

        <div className="stack" style={{ marginTop: 16 }}>
          <button className="primary wide" onClick={another}>
            Enrol another in {f.community}
          </button>
          {flash?.id && (
            <button className="wide" onClick={() => navigate(`/patients/${flash.id}`)}>
              Open her record
            </button>
          )}
          <button className="quiet wide" onClick={() => navigate('/worklist')}>
            Back to the worklist
          </button>
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <h1 style={{ margin: 0 }}>{STEPS[step]}</h1>
        <span className="spacer" />
        <span className="muted tiny">Step {step + 1} of 4</span>
      </div>

      {flash?.bad && <div className="notice bad" role="alert">{flash.text}</div>}

      <div className="card">
        {step === 0 && (
          <>
            <div className="field">
              <label htmlFor="n">Her name</label>
              <input id="n" value={f.name} onChange={set('name')}
                     autoComplete="off"
                     aria-invalid={!!errors.name} />
              {errors.name && <div className="error">{errors.name}</div>}
            </div>
            <div className="field">
              <label htmlFor="p">Her phone</label>
              <input id="p" inputMode="tel" value={f.phone} onChange={set('phone')}
                     placeholder="024 000 0001" aria-invalid={!!errors.phone} />
              {errors.phone && <div className="error">{errors.phone}</div>}
            </div>
            <div className="field">
              <label htmlFor="lang">Language she speaks</label>
              <select id="lang" value={f.language} onChange={set('language')}>
                {['dagbani', 'kusaal', 'frafra', 'gonja', 'english'].map(x =>
                  <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
              </select>
              <div className="help">Every call she gets will be in this language.</div>
            </div>
            <div className="field">
              <label htmlFor="e">Due date, if known</label>
              <input id="e" type="date" value={f.edd} onChange={set('edd')} />
              <div className="help">
                This builds her eight antenatal calls. Without it there is no
                schedule.
              </div>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <div className="field">
              <label htmlFor="c">Community</label>
              <input id="c" value={f.community} onChange={set('community')}
                     aria-invalid={!!errors.community} />
              {errors.community && <div className="error">{errors.community}</div>}
              <div className="help">Transport is matched by community.</div>
            </div>
            <div className="field">
              <label htmlFor="r">Region</label>
              <select id="r" value={f.region} onChange={set('region')}>
                {['Northern', 'North East', 'Savannah', 'Upper East', 'Upper West']
                  .map(x => <option key={x} value={x}>{x}</option>)}
              </select>
              <div className="help">Nutrition advice is filtered by region and month.</div>
            </div>
            <div className="field">
              <label htmlFor="mins">How long to the health centre, in minutes?</label>
              <input id="mins" inputMode="numeric" value={f.minutes_to_facility}
                     onChange={set('minutes_to_facility')} placeholder="45" />
              <div className="help">
                Walking or by the usual transport. This shortens the follow-up
                window for anything that could get worse.
              </div>
            </div>
            <div className="field">
              <label htmlFor="road">The road</label>
              <select id="road" value={f.road_condition} onChange={set('road_condition')}>
                <option value="good">Good — passable all year</option>
                <option value="fair">Fair</option>
                <option value="poor">Poor — hard in the rains</option>
              </select>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="field">
              <label htmlFor="sn">Second contact — name</label>
              <input id="sn" value={f.secondary_name} onChange={set('secondary_name')} />
              <div className="help">
                Who this is matters. The platform should not ring an unnamed
                number about someone's pregnancy.
              </div>
            </div>
            <div className="field">
              <label htmlFor="s">Second contact — phone</label>
              <input id="s" inputMode="tel" value={f.secondary_phone}
                     onChange={set('secondary_phone')} />
              <div className="help">Tried when she cannot be reached, before a visit.</div>
            </div>
            <div className="field">
              <label htmlFor="a">What the household can afford</label>
              <select id="a" value={f.affordability} onChange={set('affordability')}>
                <option value="low">Little to spare — free and cheap foods</option>
                <option value="medium">Can sometimes buy eggs, fish or milk</option>
              </select>
              <div className="help">
                Advice she cannot follow is not advice. This filters what the
                platform suggests.
              </div>
            </div>
            <div className="field">
              <label>Foods she will not eat</label>
              <div className="chips">
                {TABOOS.map(([k, l]) => (
                  <button type="button" key={k} className="chip"
                          aria-pressed={taboos.includes(k)}
                          onClick={() => setTaboos(t =>
                            t.includes(k) ? t.filter(x => x !== k) : [...t, k])}>
                    {l}
                  </button>
                ))}
              </div>
              <div className="help">
                The platform does not argue with a taboo on an automated call. It
                offers another food from the same group.
              </div>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <p>Read these to her and record what she agrees to.</p>
            {[
              ['calls', 'We may call her phone on a schedule about her pregnancy.', true],
              ['record', 'We may keep a record of her health information.', true],
              ['contact', 'We may call her second contact if we cannot reach her.', false],
            ].map(([key, text, required]) => (
              <label key={key} className="row"
                     style={{ gap: 12, alignItems: 'flex-start', padding: '12px 0',
                              borderBottom: '1px solid var(--line)' }}>
                <input type="checkbox" checked={consents[key]}
                       onChange={e => setConsents(c => ({ ...c, [key]: e.target.checked }))} />
                <span style={{ fontWeight: 400 }}>
                  {text}
                  {required && <strong> (needed)</strong>}
                </span>
              </label>
            ))}
            {!allConsented && (
              <div className="notice warn" style={{ marginTop: 16 }}>
                She has to agree to the calls and to the record before she can be
                enrolled. Without those there is nothing this platform can do for
                her.
              </div>
            )}
          </>
        )}
      </div>

      <div className="row" style={{ gap: 8 }}>
        {step > 0 && (
          <button className="quiet" onClick={() => setStep(s => s - 1)}>Back</button>
        )}
        <span className="spacer" />
        {step < 3 ? (
          <button className="primary" onClick={() => {
            if (step === 0 && !validate()) return
            setStep(s => s + 1)
          }}>Next</button>
        ) : (
          <button className="primary" onClick={submit} disabled={!allConsented || busy}>
            {busy ? <span className="spin" /> : 'Enrol her'}
          </button>
        )}
      </div>
    </>
  )
}
