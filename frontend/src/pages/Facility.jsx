import { useEffect, useState } from 'react'
import { BackLink } from '../App'
import CriticalAction from '../lib/CriticalAction'
import { useData, Empty, Failed, Skeleton } from '../lib/data'
import { reasonLabel } from './Worklist'

// Delay 3, made about time.
//
// The clerk's screen previously showed raw reason codes — a clerk preparing a
// resuscitation trolley read `sign.reduced_fetal_movement` — and had no notion
// of elapsed time at all, so a referral confirmed four minutes ago looked
// identical to one confirmed ninety minutes ago. Delay 3 is a delay; time is
// the one thing that has to be on screen.

function elapsed(since) {
  if (!since) return null
  const minutes = Math.max(0, Math.round((Date.now() - new Date(since)) / 60000))
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export default function Facility() {
  const { data, error, loading, reload } = useData('/api/facility/inbound',
                                                   { interval: 15000 })
  const [, tick] = useState(0)
  useEffect(() => {
    // Re-render once a minute so the clocks move without refetching.
    const t = setInterval(() => tick(n => n + 1), 60000)
    return () => clearInterval(t)
  }, [])

  if (loading && !data) return <Skeleton rows={3} />
  if (!data) return <Failed error={error} onRetry={reload} />

  const rows = data.inbound || []
  const enRoute = rows.filter(r => r.status !== 'arrived')
  const arrived = rows.filter(r => r.status === 'arrived')

  return (
    <>
      <BackLink />
      <h1>Facility</h1>
      <p className="muted">
        Who is coming, why, and how long they have been travelling.
      </p>

      <h2 className="band-head">On the way {enRoute.length > 0 && `· ${enRoute.length}`}</h2>
      {enRoute.length === 0 ? (
        <Empty title="Nobody is on the way">
          Confirmed emergencies appear here before the patient arrives.
        </Empty>
      ) : enRoute.map(r => <Case key={r.id} row={r} onDone={reload} />)}

      {arrived.length > 0 && (
        <>
          <h2 className="band-head">Arrived</h2>
          {arrived.map(r => <Case key={r.id} row={r} onDone={reload} arrived />)}
        </>
      )}
    </>
  )
}

function Case({ row, onDone, arrived = false }) {
  const waiting = elapsed(row.notified_at || row.created_at)
  const late = waiting && waiting.includes('h')

  return (
    <div className="card" style={{
      borderLeft: `6px solid var(--${arrived ? 'ok' : late ? 'emergency' : 'ochre'})`,
    }}>
      <div className="row">
        <h2 style={{ margin: 0 }}>{row.patient?.name}</h2>
        <span className="spacer" />
        {waiting && (
          <span className={`badge ${late ? 'red' : 'amber'}`}>
            {waiting}{arrived ? ' to arrive' : ' travelling'}
          </span>
        )}
      </div>
      <div className="muted tiny">{row.patient?.community}</div>

      <p style={{ margin: '12px 0 8px', fontSize: '1.05rem' }}>
        {(row.reasons || []).map(reasonLabel).join(' · ') || 'Emergency'}
      </p>

      {row.driver ? (
        <p className="tiny">
          {row.driver.name} · {row.driver.vehicle} ·{' '}
          <a href={`tel:${row.driver.phone}`}>{row.driver.phone}</a>
          {row.driver.location && <> · last reported near {row.driver.location}</>}
        </p>
      ) : (
        <p className="tiny muted">No driver has accepted yet.</p>
      )}

      {row.patient?.phone && (
        <p className="tiny">
          Her phone: <a href={`tel:${row.patient.phone}`}>{row.patient.phone}</a>
        </p>
      )}

      {!arrived && (
        <CriticalAction
          path={`/api/facility/${row.id}/arrived`}
          label="She has arrived"
          doneLabel="Arrival recorded"
          className="wide"
          onDone={onDone}
        />
      )}
      {arrived && (
        <p className="tiny muted">
          The case stays open until a health worker records what care she
          received.
        </p>
      )}
    </div>
  )
}
