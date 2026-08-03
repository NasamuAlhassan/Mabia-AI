import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, post } from '../api'
import { BackLink } from '../App'
import { outbox } from '../db'
import CriticalAction from '../lib/CriticalAction'
import CareCircle from '../components/CareCircle'
import { useData, Failed, Skeleton } from '../lib/data'
import { reasonLabel } from './Dashboard'
import { display as phone } from '../phone'
import * as I from '../components/Icons'

// Three states per sign, not two.
//
// The previous version sent every sign she had not tapped as an explicit
// clinical denial. A CHO opening the page only to enter an arm measurement
// silently asserted "no bleeding, no convulsions, no fever" as positive
// findings she had made — and those denials then cleared signs affirmed on an
// earlier call. "Not asked" and "asked and denied" are different facts, and the
// paper CHPS register has always distinguished them.

const SIGNS = [
  ['bleeding', 'Bleeding'],
  ['severe_headache', 'Bad headache or blurred vision'],
  ['convulsions', 'Convulsions'],
  ['fever', 'Fever'],
  ['reduced_fetal_movement', 'Baby moving less'],
  ['swelling', 'Swollen face or hands'],
  ['severe_abdominal_pain', 'Severe stomach pain'],
]

export default function Patient() {
  const { id } = useParams()
  const { data: p, error, loading, reload } = useData(`/api/patients/${id}`)
  const [mode, setMode] = useState('read')
  const [note, setNote] = useState('')

  if (loading && !p) return <Skeleton rows={4} />
  if (!p) return <><BackLink /><Failed error={error} onRetry={reload} /></>

  const open = (p.emergencies || []).find(e => e.status !== 'closed')
  const initials = (p.name || '').split(' ').filter(Boolean)
    .slice(0, 2).map(w => w[0]).join('').toUpperCase()
  const RISK = { red: 'HIGH RISK', amber: 'MEDIUM RISK', green: 'LOW RISK' }
  const PILL = { red: 'high', amber: 'medium', green: 'low' }

  if (mode === 'visit') {
    return (
      <>
        <BackLink to={`/patients/${p.id}`} label={`Back to ${p.name}`} />
        <VisitFlow patient={p} onDone={() => { setMode('read'); reload() }}
                   onCancel={() => setMode('read')} />
      </>
    )
  }

  return (
    <>
      <BackLink />

      <div className="person-head">
        <span className="avatar">{initials || '—'}</span>
        <span>
          <span className="row" style={{ gap: 12 }}>
            <h1>{p.name}</h1>
            <span className={`pill ${PILL[p.risk_level] || 'stable'}`}>
              {RISK[p.risk_level] || 'NOT ASSESSED'}
            </span>
          </span>
          <div className="meta">
            {p.community}
            {p.weeks_pregnant != null && ` · ${p.weeks_pregnant} weeks pregnant`}
            {` · speaks ${p.language}`}
            {p.minutes_to_facility != null && ` · ${p.minutes_to_facility} min from care`}
          </div>
        </span>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1.05fr) minmax(0,1.1fr) minmax(0,.85fr)' }}>
        {/* 1. Who she is */}
        <div>
          <div className="card">
            <div className="card-head"><I.Note size={16} /> 1. Patient information</div>
            <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
              <div className="factrow">
                <I.Baby /><span className="k">Weeks pregnant</span>
                <span className="spacer" />
                <span className="v">
                  {p.weeks_pregnant != null ? `${p.weeks_pregnant} weeks` : 'Not recorded'}
                </span>
              </div>
              <div className="factrow">
                <I.Pin /><span className="k">Location</span>
                <span className="spacer" />
                <span className="v">
                  {p.community || '—'}
                  <small>
                    {p.minutes_to_facility != null
                      ? `${p.minutes_to_facility} min from care`
                      : 'Distance not recorded'}
                  </small>
                </span>
              </div>
              <div className="factrow">
                <I.Phone /><span className="k">Phone</span>
                <span className="spacer" />
                <span className="v">
                  <a href={`tel:${p.phone}`}>{phone(p.phone)}</a>
                </span>
              </div>
              <div className="factrow">
                <I.Calendar size={16} /><span className="k">Expected delivery</span>
                <span className="spacer" />
                <span className="v">
                  {p.edd ? new Date(p.edd).toLocaleDateString() : 'Not recorded'}
                </span>
              </div>
              <div className="factrow">
                <I.Card /><span className="k">Household budget</span>
                <span className="spacer" />
                <span className="v" style={{ textTransform: 'capitalize' }}>
                  {p.affordability || 'low'}
                </span>
              </div>
              <div className="factrow">
                <I.Clock /><span className="k">Last contact</span>
                <span className="spacer" />
                <span className="v">
                  {p.last_contact_at
                    ? new Date(p.last_contact_at).toLocaleDateString() : 'Never'}
                </span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><I.Circle size={16} /> 3. History</div>
            <div className="card-body"><History patient={p} /></div>
          </div>
        </div>

        {/* 2. Why she is where she is */}
        <div>
          <div className={`card ${p.risk_level === 'red' ? 'riskpanel' : ''}`}>
            <div className="card-head"><I.Warning size={16} /> 2. Risk status</div>
            <div className="card-body">
              <div className="riskbig">
                {p.risk_level === 'red' && <I.Warning size={38} />}
                <span className="lvl" style={p.risk_level !== 'red'
                  ? { color: p.risk_level === 'amber' ? 'var(--medium)' : 'var(--low)' } : undefined}>
                  {RISK[p.risk_level] || 'NOT ASSESSED'}
                </span>
              </div>

              {p.reason_codes?.length > 0 ? (
                <>
                  <div className="riskwhy"
                       style={p.risk_level !== 'red' ? { color: 'var(--ink)' } : undefined}>
                    Why is she at this level?
                  </div>
                  <ul>{p.reason_codes.map(r => <li key={r}>{reasonLabel(r)}</li>)}</ul>
                </>
              ) : (
                <p className="muted tiny" style={{ margin: 0 }}>
                  Nothing has been reported that needs a visit. This is a
                  result, not an absence of data.
                </p>
              )}

              <div className="tiny muted" style={{ marginTop: 14 }}>
                Every reason here came from something she said or something a
                worker measured. Nothing is inferred.
              </div>
            </div>
          </div>

          {open && (
            <div className="card">
              <div className="card-head alarm">
                <I.Warning size={16} /> Open emergency
              </div>
              <div className="card-body">
                <p className="muted tiny" style={{ marginTop: 0 }}>
                  Status: {open.status.replace(/_/g, ' ')}. It stays open until a
                  person records what actually happened.
                </p>
                {open.alert_failed && (
                  <div className="notice bad tiny" style={{ marginBottom: 12 }}>
                    The text message to her health worker did not send. Reach
                    her another way.
                  </div>
                )}
                <Outcome id={open.id} onDone={reload} />
              </div>
            </div>
          )}

        </div>

        {/* 3. What she can do about it */}
        <div>
          <div className="card">
            <div className="card-head">Actions</div>
            <div className="card-body stack">
              <button className="primary wide" onClick={() => setMode('visit')}>
                <I.Note size={16} /> Record a visit
              </button>
              <button className="wide" onClick={() => window.location.assign(`tel:${p.phone}`)}>
                <I.Phone size={16} /> Call her
              </button>
              <button className="wide" onClick={() => window.location.assign('/visits/facility')}>
                <I.Car size={16} /> Facility board
              </button>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><I.Note size={16} /> Quick note</div>
            <div className="card-body stack">
              <textarea rows={4} value={note} aria-label="Quick note"
                        placeholder="Add a note for the next visit…"
                        onChange={e => setNote(e.target.value)} />
              <p className="muted tiny" style={{ margin: 0 }}>
                Notes are saved with a visit, so they carry the date and who
                wrote them. Record a visit to keep this.
              </p>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><I.Chart size={16} /> Key summary</div>
            <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
              <div className="summary-row">
                <span className="k">Risk level</span><span className="spacer" />
                <span className={`pill ${PILL[p.risk_level] || 'stable'}`}>
                  {(p.risk_level || '—').toUpperCase()}
                </span>
              </div>
              <div className="summary-row">
                <span className="k">Weeks pregnant</span><span className="spacer" />
                <span className="v">{p.weeks_pregnant ?? '—'}</span>
              </div>
              <div className="summary-row">
                <span className="k">Distance to facility</span><span className="spacer" />
                <span className="v">
                  {p.minutes_to_facility != null
                    ? `${p.minutes_to_facility} min` : 'Not recorded'}
                </span>
              </div>
              <div className="summary-row">
                <span className="k">Dietary diversity</span><span className="spacer" />
                <span className="v">
                  {p.mdd_score != null
                    ? `${p.mdd_score} of ${p.mdd_instrument === 'mdd_child' ? 8 : 10}`
                    : 'Not measured'}
                </span>
              </div>
              <div className="summary-row">
                <span className="k">Iron and folic acid</span><span className="spacer" />
                <span className="v">
                  {p.ifa_adherent === true ? 'Taking'
                    : p.ifa_adherent === false ? 'Not taking' : 'Not asked'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><I.People size={16} /> 4. Care circle</div>
        <div className="card-body"><CareCircle patientId={p.id} /></div>
      </div>
    </>
  )
}


function VisitFlow({ patient, onDone, onCancel }) {
  const [answers, setAnswers] = useState({})     // key -> true | false (absent = not asked)
  const [muacMother, setMuacMother] = useState('')
  const [muacChild, setMuacChild] = useState('')
  const [ifa, setIfa] = useState('')
  const [note, setNote] = useState('')
  const [state, setState] = useState('idle')
  const [message, setMessage] = useState('')

  const asked = Object.keys(answers).length

  async function save() {
    setState('busy'); setMessage('')
    const body = {
      signs: Object.entries(answers).filter(([, v]) => v).map(([k]) => k),
      denied: Object.entries(answers).filter(([, v]) => v === false).map(([k]) => k),
      muac_mother: muacMother ? parseFloat(muacMother) : null,
      muac_child: muacChild ? parseFloat(muacChild) : null,
      ifa_adherent: ifa === '' ? null : ifa === 'yes',
      note: note || null,
      occurred_at: new Date().toISOString(),
    }
    try {
      await post(`/api/patients/${patient.id}/observations`, body)
      setState('done')
      setMessage(`Saved for ${patient.name} at ${new Date().toLocaleTimeString(
        [], { hour: '2-digit', minute: '2-digit' })}.`)
      setTimeout(onDone, 1200)
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        // Queue ALL of it. The previous version queued only the danger signs
        // and dropped the arm measurement, the iron answer and the note — while
        // telling her it had been saved.
        await outbox.add({
          patient_id: patient.id, event_type: 'visit_recorded',
          payload: body, occurred_at: body.occurred_at,
        })
        setState('queued')
        setMessage('No signal. The whole visit is saved on this phone and will '
                   + 'send when you have a bar.')
        setTimeout(onDone, 1800)
      } else {
        setState('failed')
        setMessage(`Not saved: ${e.message}. Nothing was recorded — try again.`)
      }
    }
  }

  return (
    <div className="card">
      <div className="row">
        <h2 style={{ margin: 0 }}>Record a visit</h2>
        <span className="spacer" />
        <button className="quiet small" onClick={onCancel}>Cancel</button>
      </div>

      <p className="muted tiny">
        Only tap what you actually checked. Anything you leave blank is recorded
        as “not asked”, not as “no”.
      </p>

      {SIGNS.map(([key, label]) => (
        <fieldset key={key} style={{ border: 0, padding: 0, margin: '0 0 12px' }}>
          <legend style={{ fontWeight: 700, fontSize: '.95rem', padding: 0 }}>
            {label}
          </legend>
          <div className="chips" style={{ marginTop: 6 }}>
            {[['yes', true], ['no', false]].map(([word, value]) => (
              <button type="button" key={word}
                      className="chip"
                      aria-pressed={answers[key] === value}
                      onClick={() => setAnswers(a => (
                        a[key] === value
                          ? Object.fromEntries(Object.entries(a).filter(([k]) => k !== key))
                          : { ...a, [key]: value }))}>
                {word === 'yes' ? 'Yes' : 'No'}
              </button>
            ))}
            {answers[key] === undefined && (
              <span className="muted tiny" style={{ alignSelf: 'center' }}>
                not asked
              </span>
            )}
          </div>
        </fieldset>
      ))}

      <div className="row wrap" style={{ gap: 12 }}>
        <div className="field" style={{ flex: 1, minWidth: 140 }}>
          <label htmlFor="mm">Her arm measure (MUAC, cm)</label>
          <input id="mm" inputMode="decimal" value={muacMother}
                 onChange={e => setMuacMother(e.target.value)} placeholder="22.5" />
          <div className="help">Below 23 cm needs follow-up.</div>
        </div>
        <div className="field" style={{ flex: 1, minWidth: 140 }}>
          <label htmlFor="mc">Child’s arm measure (cm)</label>
          <input id="mc" inputMode="decimal" value={muacChild}
                 onChange={e => setMuacChild(e.target.value)} placeholder="12.1" />
          <div className="help">Below 11.5 cm is severe.</div>
        </div>
      </div>

      <div className="field">
        <label htmlFor="ifa">Taking her iron and folic acid?</label>
        <select id="ifa" value={ifa} onChange={e => setIfa(e.target.value)}>
          <option value="">Not asked</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      </div>

      <div className="field">
        <label htmlFor="note">Anything else</label>
        <textarea id="note" value={note} onChange={e => setNote(e.target.value)} />
      </div>

      {message && (
        <div className={`notice ${state === 'failed' ? 'bad'
                        : state === 'queued' ? 'warn' : 'ok'}`} role="status">
          {message}
        </div>
      )}

      {/* The commit sits at the bottom, where her thumb already is, and the
          result appears immediately above it rather than 700px up the page. */}
      <button className="primary wide" onClick={save}
              disabled={state === 'busy' || state === 'done'}>
        {state === 'busy' ? <span className="spin" />
          : asked || muacMother || muacChild || ifa || note
            ? 'Save visit' : 'Save visit (nothing recorded yet)'}
      </button>
    </div>
  )
}

function Outcome({ id, onDone }) {
  const [outcome, setOutcome] = useState('care_received')
  const [note, setNote] = useState('')
  return (
    <div className="stack">
      <div className="field" style={{ margin: 0 }}>
        <label htmlFor="outcome">What happened?</label>
        <select id="outcome" value={outcome}
                onChange={e => setOutcome(e.target.value)}>
          <option value="care_received">She reached care</option>
          <option value="not_reached">She did not reach the facility</option>
          <option value="refused">The family declined</option>
          <option value="other">Something else</option>
        </select>
      </div>
      <div className="field" style={{ margin: 0 }}>
        <label htmlFor="outcome-note">Details</label>
        <input id="outcome-note" value={note}
               onChange={e => setNote(e.target.value)} />
      </div>
      <CriticalAction path={`/api/emergencies/${id}/outcome`}
                      body={{ outcome, note }}
                      label="Close the loop"
                      doneLabel="Outcome recorded"
                      onDone={onDone} />
    </div>
  )
}

function History({ patient }) {
  // No card and no heading of its own: it is rendered inside one now.
  return (
    <>
      <p className="muted tiny" style={{ marginTop: 0 }}>
        {patient.state?.events_folded ?? 0} records, newest first. Nothing here
        has ever been overwritten.
      </p>
      <div className="timeline">
        {[...(patient.events || [])].reverse().map(e => (
          <div className="item" key={e.event_id}>
            <div style={{ fontWeight: 600 }}>{title(e)}</div>
            <div className="when">
              {new Date(e.occurred_at).toLocaleString()}
            </div>
            {detail(e) && <div className="tiny muted">{detail(e)}</div>}
          </div>
        ))}
      </div>
    </>
  )
}

const TITLES = {
  enrolment: 'Enrolled', consent_given: 'Consent recorded',
  danger_signs_reported: 'Danger signs checked', diet_recall: 'Diet asked about',
  muac_measured: 'Arm measured', ifa_adherence: 'Iron tablets asked about',
  visit_recorded: 'Visit', call_attempted: 'Call attempted',
  call_completed: 'Call completed', emergency_raised: 'Emergency raised',
  emergency_validated: 'Emergency confirmed', referral_outcome: 'Outcome recorded',
  nurse_routed: 'Routed to a nurse',
}

const title = (e) => TITLES[e.type] || e.type.replace(/_/g, ' ')

function detail(e) {
  const p = e.payload || {}
  if (e.type === 'danger_signs_reported') {
    const parts = []
    if (p.signs?.length) parts.push(`reported: ${p.signs.join(', ')}`)
    if (p.denied?.length) parts.push(`denied: ${p.denied.join(', ')}`)
    if (p.unanswered?.length) parts.push(`no answer: ${p.unanswered.join(', ')}`)
    return parts.join(' · ') || 'nothing reported'
  }
  if (e.type === 'diet_recall') {
    return `${p.instrument === 'mdd_w' ? 'MDD-W' : 'child'} ${p.score}/${p.total}`
      + (p.message ? ` — advised: ${p.message.slice(0, 70)}…` : '')
  }
  if (e.type === 'muac_measured') return `${p.subject}: ${p.value_cm} cm`
  if (e.type === 'ifa_adherence') return p.adherent ? 'taking them' : 'not taking them'
  if (e.type === 'call_attempted') return p.outcome
  if (e.type === 'referral_outcome') return `${p.outcome}${p.note ? ` — ${p.note}` : ''}`
  return p.note || ''
}
