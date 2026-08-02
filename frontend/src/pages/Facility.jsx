import { useEffect, useState } from 'react'
import { get, post } from '../api'

// Delay 3. The facility should not learn of a case at the door.

export default function Facility() {
  const [rows, setRows] = useState([])
  const load = () => get('/api/facility/inbound').then(d => setRows(d.inbound)).catch(() => {})
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t) }, [])

  return (
    <>
      <h1>Facility</h1>
      <p className="muted">
        Incoming cases, with the reasons ahead of the patient so resources can be
        ready before she arrives.
      </p>
      {rows.length === 0 && <div className="card muted">Nothing inbound.</div>}
      {rows.map(r => (
        <div className="card stripe red" key={r.id}>
          <div className="row">
            <h2 style={{ margin: 0 }}>{r.patient?.name}</h2>
            <span className="spacer" />
            <span className="badge amber">{r.status.replace(/_/g, ' ')}</span>
          </div>
          <div className="muted tiny">{r.patient?.community} · {r.patient?.phone}</div>
          <div className="chips" style={{ margin: '.5rem 0' }}>
            {(r.reasons || []).map(x => <span className="chip" key={x}>{x}</span>)}
          </div>
          {r.driver ? (
            <p className="tiny">
              Transport: <strong>{r.driver.name}</strong> ({r.driver.vehicle}) ·{' '}
              {r.driver.phone}
              {r.driver.location && <> · last reported: {r.driver.location}</>}
            </p>
          ) : <p className="tiny muted">No driver accepted yet.</p>}
          <button className="wide" onClick={async () => {
            await post(`/api/facility/${r.id}/arrived`); load()
          }}>Mark arrived</button>
        </div>
      ))}
    </>
  )
}
