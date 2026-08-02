import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { get, post } from '../api'
import { outbox } from '../db'
import { reasonLabel } from './Worklist'

const SIGNS = [
  ['bleeding', 'Bleeding'], ['severe_headache', 'Headache / blurred vision'],
  ['convulsions', 'Convulsions'], ['fever', 'Fever'],
  ['reduced_fetal_movement', 'Baby moving less'], ['swelling', 'Swelling'],
  ['severe_abdominal_pain', 'Severe abdominal pain'],
]

export default function Patient() {
  const { id } = useParams()
  const [p, setP] = useState(null)
  const [signs, setSigns] = useState([])
  const [muacMother, setMuacMother] = useState('')
  const [muacChild, setMuacChild] = useState('')
  const [ifa, setIfa] = useState('')
  const [note, setNote] = useState('')
  const [flash, setFlash] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = () => get(`/api/patients/${id}`).then(setP).catch(() => {})
  useEffect(() => { load() }, [id])

  async function record() {
    setBusy(true); setFlash(null)
    const body = {
      signs,
      denied: SIGNS.map(([k]) => k).filter(k => !signs.includes(k)),
      muac_mother: muacMother ? parseFloat(muacMother) : null,
      muac_child: muacChild ? parseFloat(muacChild) : null,
      ifa_adherent: ifa === '' ? null : ifa === 'yes',
      note: note || null,
      occurred_at: new Date().toISOString(),
    }
    try {
      setP(await post(`/api/patients/${id}/observations`, body))
      setFlash({ text: 'Recorded.' })
      setSigns([]); setMuacMother(''); setMuacChild(''); setIfa(''); setNote('')
    } catch (e) {
      // No signal: queue it. The server de-duplicates, so a later flush is safe.
      await outbox.add({
        patient_id: id, event_type: 'danger_signs_reported',
        payload: { signs: body.signs, denied: body.denied, source: 'visit' },
        occurred_at: body.occurred_at,
      })
      setFlash({ warn: true, text: 'No signal — saved on this device and queued to sync.' })
    } finally { setBusy(false) }
  }

  if (!p) return <div className="center muted"><span className="spin" /></div>

  const open = (p.emergencies || []).find(e => e.status !== 'closed')

  return (
    <>
      <div className="row">
        <h1 style={{ margin: 0 }}>{p.name}</h1>
        <span className="spacer" />
        <span className={`badge ${p.risk_level}`}>{p.risk_level}</span>
      </div>
      <p className="muted">{p.community} · {p.language} · {p.phone}
        {p.edd && <> · due {new Date(p.edd).toLocaleDateString()}</>}</p>

      {flash && <div className={`notice ${flash.warn ? 'warn' : 'ok'}`}>{flash.text}</div>}

      {p.reason_codes?.length > 0 && (
        <div className={`card stripe ${p.risk_level}`}>
          <h2>Why</h2>
          <div className="chips">
            {p.reason_codes.map(r => <span className="chip" key={r}>{reasonLabel(r)}</span>)}
          </div>
          <p className="muted tiny" style={{ marginTop: '.5rem' }}>
            Reasons travel with every classification, so you are checking a
            judgement rather than obeying a score.
          </p>
        </div>
      )}

      {open && (
        <div className="card stripe red">
          <h2>Open emergency</h2>
          <p className="muted tiny">Status: {open.status.replace(/_/g, ' ')}</p>
          <Outcome id={open.id} onDone={load} />
        </div>
      )}

      <div className="card">
        <h2>Record a visit</h2>
        <label>Danger signs</label>
        <div className="chips" style={{ marginBottom: '.8rem' }}>
          {SIGNS.map(([k, l]) => (
            <button type="button" key={k}
                    className={`chip ${signs.includes(k) ? 'on' : ''}`}
                    onClick={() => setSigns(s =>
                      s.includes(k) ? s.filter(x => x !== k) : [...s, k])}>
              {l}
            </button>
          ))}
        </div>
        <div className="row wrap" style={{ gap: '.6rem' }}>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="mm">Mother MUAC (cm)</label>
            <input id="mm" inputMode="decimal" value={muacMother}
                   onChange={e => setMuacMother(e.target.value)} placeholder="e.g. 22.5" />
          </div>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="mc">Child MUAC (cm)</label>
            <input id="mc" inputMode="decimal" value={muacChild}
                   onChange={e => setMuacChild(e.target.value)} placeholder="e.g. 12.1" />
          </div>
        </div>
        <div className="field">
          <label htmlFor="ifa">Taking iron and folic acid?</label>
          <select id="ifa" value={ifa} onChange={e => setIfa(e.target.value)}>
            <option value="">Not asked</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="note">Note</label>
          <textarea id="note" value={note} onChange={e => setNote(e.target.value)} />
        </div>
        <button className="primary wide" onClick={record} disabled={busy}>
          {busy ? <span className="spin" /> : 'Save visit'}
        </button>
      </div>

      <div className="card">
        <h2>History</h2>
        <p className="muted tiny">
          Append-only. {p.state?.events_folded ?? 0} events folded into the state
          above — nothing here was ever overwritten.
        </p>
        <div className="timeline">
          {[...(p.events || [])].reverse().map(e => (
            <div className="event" key={e.event_id}>
              <strong>{e.type.replace(/_/g, ' ')}</strong>{' '}
              <span className="muted tiny">
                {new Date(e.occurred_at).toLocaleString()} · {e.device}
              </span>
              <div className="muted tiny">{summarise(e)}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

function summarise(e) {
  const p = e.payload || {}
  if (e.type === 'danger_signs_reported') {
    return p.signs?.length ? `reported: ${p.signs.join(', ')}` : 'none reported'
  }
  if (e.type === 'diet_recall') {
    return `${p.instrument === 'mdd_w' ? 'MDD-W' : 'child MDD'} ${p.score}/${p.total}` +
           (p.message ? ` — advised: ${p.message.slice(0, 80)}…` : '')
  }
  if (e.type === 'muac_measured') return `${p.subject}: ${p.value_cm} cm`
  if (e.type === 'ifa_adherence') return p.adherent ? 'taking tablets' : 'not taking tablets'
  if (e.type === 'call_attempted') return p.outcome
  if (e.type === 'referral_outcome') return `${p.outcome}${p.note ? ` — ${p.note}` : ''}`
  return p.note || ''
}

function Outcome({ id, onDone }) {
  const [outcome, setOutcome] = useState('care_received')
  const [note, setNote] = useState('')
  return (
    <div className="stack">
      <p className="muted tiny">
        The case stays open until this is recorded. Proof of care, not just advice.
      </p>
      <select value={outcome} onChange={e => setOutcome(e.target.value)}>
        <option value="care_received">Care was received</option>
        <option value="not_reached">Did not reach the facility</option>
        <option value="refused">Family declined</option>
        <option value="other">Other</option>
      </select>
      <input placeholder="What happened?" value={note}
             onChange={e => setNote(e.target.value)} />
      <button className="primary" onClick={async () => {
        await post(`/api/emergencies/${id}/outcome`, { outcome, note }); onDone()
      }}>Close the loop</button>
    </div>
  )
}
