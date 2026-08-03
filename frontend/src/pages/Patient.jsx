import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, post } from '../api'
import { BackLink } from '../App'
import { outbox } from '../db'
import CriticalAction from '../lib/CriticalAction'
import CareCircle from '../components/CareCircle'
import { useData, Failed, Skeleton } from '../lib/data'
import { reasonLabel } from './Worklist'

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

  if (loading && !p) return <Skeleton rows={4} />
  if (!p) return <><BackLink /><Failed error={error} onRetry={reload} /></>

  const open = (p.emergencies || []).find(e => e.status !== 'closed')

  return (
    <>
      <BackLink />

      <div className="row">
        <h1 style={{ margin: 0 }}>{p.name}</h1>
        <span className="spacer" />
        <span className={`badge ${p.risk_level}`}>
          {p.risk_level === 'red' ? 'See now'
            : p.risk_level === 'amber' ? 'See today' : 'Routine'}
        </span>
      </div>
      <p className="muted">
        {p.community} · speaks {p.language} ·{' '}
        <a href={`tel:${p.phone}`}>{p.phone}</a>
        {p.edd && <> · due {new Date(p.edd).toLocaleDateString()}</>}
      </p>

      {p.reason_codes?.length > 0 && (
        <div className="card" style={{
          borderLeft: `6px solid var(--${p.risk_level === 'red' ? 'emergency' : 'ochre'})`,
        }}>
          <h2>Why she is flagged</h2>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {p.reason_codes.map(r => <li key={r}>{reasonLabel(r)}</li>)}
          </ul>
        </div>
      )}

      {open && (
        <div className="card" style={{ borderLeft: '6px solid var(--emergency)' }}>
          <h2>Open emergency</h2>
          <p className="muted tiny">
            Status: {open.status.replace(/_/g, ' ')}. It stays open until you
            record what happened.
          </p>
          <Outcome id={open.id} onDone={reload} />
        </div>
      )}

      {mode === 'read' ? (
        <>
          <button className="primary wide" onClick={() => setMode('visit')}>
            Record a visit
          </button>
          <CareCircle patientId={p.id} />
          <History patient={p} />
        </>
      ) : (
        <VisitFlow patient={p} onDone={() => { setMode('read'); reload() }}
                   onCancel={() => setMode('read')} />
      )}
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
  return (
    <div className="card">
      <h2>History</h2>
      <p className="muted tiny">
        {patient.state?.events_folded ?? 0} records, newest first. Nothing here
        has ever been overwritten.
      </p>
      <div className="timeline">
        {[...(patient.events || [])].reverse().map(e => (
          <div className="event" key={e.event_id}>
            <div className="head">{title(e)}</div>
            <div className="muted tiny">
              {new Date(e.occurred_at).toLocaleString()}
            </div>
            {detail(e) && <div className="tiny">{detail(e)}</div>}
          </div>
        ))}
      </div>
    </div>
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
