import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'

// RED first, then AMBER, then the rest. The sort is trivial; the value is that
// a worker opens the app and knows who to see, instead of reading a list.

const LABEL = {
  'sign.bleeding': 'Bleeding',
  'sign.convulsions': 'Convulsions',
  'sign.severe_headache': 'Headache, blurred vision',
  'sign.reduced_fetal_movement': 'Baby moving less',
  'sign.water_broken': 'Waters broken',
  'sign.severe_abdominal_pain': 'Severe abdominal pain',
  'sign.difficulty_breathing': 'Difficulty breathing',
  'sign.fever': 'Fever',
  'sign.swelling': 'Swelling',
  'muac.mother_low': 'Mother MUAC < 23 cm',
  'muac.child_moderate': 'Child MUAC < 12.5 cm',
  'muac.child_severe': 'Child MUAC < 11.5 cm — CMAM',
  'diet.persistently_low': 'Diet low twice running',
  'ifa.not_adherent': 'Not taking iron tablets',
  'contact.unreachable': 'Unreachable three times',
  'access.remote': 'Far from care',
  'emergency.open': 'Emergency still open',
  'hotline.nurse_unreachable': 'Could not reach a nurse',
}

export const reasonLabel = (code) => LABEL[code] || code

export default function Worklist() {
  const [data, setData] = useState(null)
  const [emergencies, setEmergencies] = useState([])
  const [error, setError] = useState('')

  async function load() {
    try {
      setData(await get('/api/worklist'))
      setEmergencies(await get('/api/emergencies'))
      setError('')
    } catch (e) {
      setError(e.message === 'offline'
        ? 'Offline — showing nothing rather than something stale.'
        : e.message)
    }
  }

  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t) }, [])

  if (error) return <div className="notice warn">{error}</div>
  if (!data) return <div className="center muted"><span className="spin" /></div>

  const pending = emergencies.filter(e => e.status === 'pending_validation')

  return (
    <>
      <h1>Worklist</h1>

      <div className="counts">
        {['red', 'amber', 'green'].map(level => (
          <div className={`count ${level}`} key={level}>
            <div className="n">{data.counts[level] ?? 0}</div>
            <div className="l">{level}</div>
          </div>
        ))}
      </div>

      {pending.length > 0 && (
        <div className="card stripe red">
          <h2>Waiting for you to confirm</h2>
          <p className="muted tiny">
            Nothing dispatches until a person confirms it. That is the gate.
          </p>
          {pending.map(em => (
            <div className="stack" key={em.id} style={{ marginTop: '.6rem' }}>
              <div>
                <strong>{em.patient?.name}</strong>{' '}
                <span className="muted">· {em.patient?.community}</span>
              </div>
              <div className="chips">
                {em.reasons.map(r => (
                  <span className="chip" key={r}>{reasonLabel(r)}</span>
                ))}
              </div>
              <button className="danger wide" onClick={async () => {
                await post(`/api/emergencies/${em.id}/validate`); load()
              }}>
                Confirm emergency and call a driver
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="list">
        {data.patients.map(p => (
          <Link className={`item stripe ${p.risk_level}`} to={`/patients/${p.id}`} key={p.id}>
            <div className="row">
              <span className="name">{p.name}</span>
              <span className="spacer" />
              <span className={`badge ${p.risk_level}`}>{p.risk_level}</span>
            </div>
            <div className="muted tiny">{p.community} · {p.language}</div>
            {p.reason_codes.length > 0 && (
              <div className="chips" style={{ marginTop: '.4rem' }}>
                {p.reason_codes.slice(0, 3).map(r => (
                  <span className="chip" key={r}>{reasonLabel(r)}</span>
                ))}
              </div>
            )}
          </Link>
        ))}
      </div>

      <div className="row" style={{ marginTop: '1rem', gap: '.5rem' }}>
        <Link className="btn" to="/facility">Facility view</Link>
        <Link className="btn" to="/metrics">Impact</Link>
      </div>
    </>
  )
}
