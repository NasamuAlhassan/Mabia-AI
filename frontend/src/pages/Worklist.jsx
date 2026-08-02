import { Link } from 'react-router-dom'
import { useData, Failed, Skeleton, Empty } from '../lib/data'
import CriticalAction from '../lib/CriticalAction'

// A queue of people, not a dashboard.
//
// The previous version led with the word "Worklist" at 24px — the largest text
// on a screen whose most important content is the name of the woman she must
// reach first — followed by three dead KPI tiles labelled "red", "amber",
// "green". Those are database values, not instructions.
//
// So this is banded by what she should do, in the order she should do it:
// an emergency takes the whole top of the screen; today is a plain list of
// rows; routine is collapsed. Urgency is carried by ink and position, so it
// survives greyscale, a bad projector, and colour-blindness.

const REASONS = {
  'sign.bleeding': 'Bleeding',
  'sign.convulsions': 'Convulsions',
  'sign.severe_headache': 'Bad headache, blurred vision',
  'sign.reduced_fetal_movement': 'Baby moving less',
  'sign.water_broken': 'Waters broken',
  'sign.severe_abdominal_pain': 'Severe stomach pain',
  'sign.difficulty_breathing': 'Struggling to breathe',
  'sign.unconscious': 'Lost consciousness',
  'sign.fever': 'Fever',
  'sign.swelling': 'Swollen face and hands',
  'sign.severe_vomiting': 'Vomiting a lot',
  'muac.mother_low': 'Her arm measure is low',
  'muac.child_moderate': 'Child’s arm measure is low',
  'muac.child_severe': 'Child severely malnourished',
  'diet.persistently_low': 'Poor diet twice running',
  'ifa.not_adherent': 'Not taking iron tablets',
  'contact.unreachable': 'No answer three times',
  'access.remote': 'Far from care on a poor road',
  'access.slow': 'A long way from care',
  'emergency.open': 'Emergency still open',
  'hotline.nurse_unreachable': 'Could not reach a nurse',
}

export const reasonLabel = (code) => REASONS[code] || code

const WHEN = { red: 'See now', amber: 'See today', green: 'Routine' }

export default function Worklist() {
  const list = useData('/api/worklist', { interval: 20000 })
  const emergencies = useData('/api/emergencies', { interval: 20000 })

  if (list.loading && !list.data) return <Skeleton rows={5} />
  if (!list.data) return <Failed error={list.error} onRetry={list.reload} />

  const patients = list.data.patients || []
  const pending = (emergencies.data || []).filter(
    e => e.status === 'pending_validation')
  const today = patients.filter(p => p.risk_level === 'amber')
  const routine = patients.filter(p => p.risk_level === 'green')
  const red = patients.filter(p => p.risk_level === 'red')

  return (
    <>
      {pending.map(em => (
        <section className="emergency-band" key={em.id} aria-label="Emergency">
          <div className="kicker">Emergency — waiting for you</div>
          <div className="who">{em.patient?.name}</div>
          <div className="where">{em.patient?.community}</div>
          <div className="why">
            {(em.reasons || []).map(reasonLabel).join(' · ') || 'Danger signs reported'}
          </div>
          <CriticalAction
            path={`/api/emergencies/${em.id}/validate`}
            label="Confirm and call a driver"
            busyLabel="Calling a driver…"
            doneLabel="Driver called"
            className=""
            holdMs={700}
            onDone={() => { emergencies.reload(); list.reload() }}
          />
        </section>
      ))}

      {red.filter(p => !pending.some(e => e.patient?.id === p.id)).length > 0 && (
        <>
          <h2 className="band-head">Emergency</h2>
          {red.filter(p => !pending.some(e => e.patient?.id === p.id))
              .map(p => <Person key={p.id} patient={p} band="today" />)}
        </>
      )}

      <h2 className="band-head">
        See today {today.length > 0 && <span>· {today.length}</span>}
      </h2>
      {today.length === 0 ? (
        <Empty title="Nobody needs a visit today">
          Everyone on your list has been reached and is stable.
        </Empty>
      ) : today.map(p => <Person key={p.id} patient={p} band="today" />)}

      {routine.length > 0 && <RoutineBand people={routine} />}

      <div className="row wrap" style={{ gap: 8, marginTop: 40 }}>
        <Link className="btn" to="/facility">Facility</Link>
        <Link className="btn" to="/metrics">What this has changed</Link>
      </div>
    </>
  )
}

function Person({ patient, band }) {
  const reasons = (patient.reason_codes || []).map(reasonLabel)
  return (
    <Link className={`person ${band}`} to={`/patients/${patient.id}`}>
      <div className="row">
        <span className="name">{patient.name}</span>
        <span className="spacer" />
        <span className="when">{WHEN[patient.risk_level]}</span>
      </div>
      <div className="meta">
        {patient.community}
        {patient.language && ` · speaks ${patient.language}`}
      </div>
      {reasons.length > 0 && (
        <div className="why">{reasons.join(' · ')}</div>
      )}
    </Link>
  )
}

function RoutineBand({ people }) {
  return (
    <details style={{ marginTop: 24 }}>
      <summary className="disclosure" style={{ cursor: 'pointer' }}>
        {people.length} routine {people.length === 1 ? 'visit' : 'visits'}
      </summary>
      {people.map(p => <Person key={p.id} patient={p} band="routine" />)}
    </details>
  )
}
