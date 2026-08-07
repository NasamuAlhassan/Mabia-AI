import { useState } from 'react'
import { patch, post } from '../api'
import { useData, ago, Empty, Failed, Skeleton } from '../lib/data'
import { display as phone } from '../phone'
import * as I from '../components/Icons'

// Delay 2: reaching care.
//
// All of this was already in the database and none of it was on a screen.
// There was no route that could list a driver, so a worker had no way to see
// who would be rung for her patient, no way to add the man with the motorking
// who everyone in the village already calls, and no way to find out that a
// community had four women enrolled and nothing registered that could carry
// one of them.
//
// On the map. No driver in this system has coordinates, because riders in
// villages are on feature phones that emit nothing, and dispatch has always
// worked on community rather than position. So the map here is drawn on the
// axis that Delay 2 is actually about: how long a village is from care. A
// scatter of invented pins would look more like a map and be a lie in the one
// screen where a lie costs a vehicle.

const VEHICLE_LABEL = {
  ambulance: 'Ambulance', car: 'Car', motorking: 'Motorking',
  motorbike: 'Motorbike', tricycle: 'Tricycle', bicycle: 'Bicycle',
}

// A bicycle is in the list because people register one; it is not counted as
// cover because it cannot carry a woman in labour.
const CARRIES = ['ambulance', 'car', 'motorking', 'motorbike', 'tricycle']

export default function Transport() {
  const roster = useData('/api/drivers?include_retired=true')
  const coverage = useData('/api/drivers/map', { interval: 60000 })
  const [adding, setAdding] = useState(false)

  if (roster.loading && !roster.data) return <Skeleton rows={4} />
  if (!roster.data) return <Failed error={roster.error} onRetry={roster.reload} />

  const drivers = roster.data.drivers || []
  const communities = coverage.data?.communities || []
  const uncovered = coverage.data?.uncovered || []
  const onRun = drivers.filter(d => d.on_run)
  const reload = () => { roster.reload(); coverage.reload() }

  return (
    <>
      <h1>Transport</h1>
      <p className="muted">
        Who can carry a woman to a facility, from which village, and how long
        that journey takes.
      </p>

      {uncovered.length > 0 && (
        <div className="notice bad" role="alert">
          <strong>
            {uncovered.length === 1 ? 'One community has' : `${uncovered.length} communities have`}
            {' '}women enrolled and no vehicle that can carry them.
          </strong>{' '}
          {uncovered.join(', ')}. Register a driver there before someone needs one.
        </div>
      )}

      {onRun.length > 0 && (
        <>
          <h2 className="band-head">On the road now · {onRun.length}</h2>
          {onRun.map(d => <Run key={d.id} driver={d} onDone={reload} />)}
        </>
      )}

      <h2 className="band-head">Time from care</h2>
      <Coverage communities={communities} loading={coverage.loading} />

      <h2 className="band-head">
        The roster · {drivers.filter(d => d.available).length} available
      </h2>
      <Roster drivers={drivers} onChange={reload} />

      <div className="row" style={{ marginTop: 16 }}>
        <button className={adding ? 'quiet' : 'primary'}
                onClick={() => setAdding(a => !a)}>
          {adding ? 'Cancel' : 'Register a driver'}
        </button>
      </div>
      {adding && (
        <AddDriver
          communities={communities.map(c => c.community)}
          onDone={() => { setAdding(false); reload() }}
        />
      )}
    </>
  )
}

/* ------------------------------------------------------------- the map
 *
 * One axis, in walking minutes, because that is the unit a CHO knows and a
 * kilometre on a bad road is not a kilometre. A village sits where its
 * furthest household sits — a mean would hide the compound an hour out.
 */

function Coverage({ communities, loading }) {
  if (!communities.length) {
    return loading ? <Skeleton rows={2} /> : (
      <Empty title="No communities yet">
        Villages appear here once women are enrolled in them.
      </Empty>
    )
  }

  const furthest = Math.max(60, ...communities.map(c => c.minutes_to_facility || 0))
  const ticks = [0, Math.round(furthest / 2), furthest]

  return (
    <div className="card">
      <div className="tmap">
        {communities.map(c => (
          <Place key={c.community} place={c} furthest={furthest} />
        ))}

        <div className="tmap__axis" aria-hidden="true">
          <span className="tmap__label" />
          <div className="tmap__ticks">
            {ticks.map((t, i) => (
              <span key={t} style={{ left: `${(t / furthest) * 100}%`,
                                     transform: i === ticks.length - 1
                                       ? 'translateX(-100%)' : i ? 'translateX(-50%)' : 'none' }}>
                {t === 0 ? 'At the facility' : `${t} min`}
              </span>
            ))}
          </div>
          <span className="tmap__count" />
        </div>
      </div>
    </div>
  )
}

function Place({ place, furthest }) {
  const minutes = place.minutes_to_facility
  const at = minutes === null || minutes === undefined
    ? null : Math.min(100, (minutes / furthest) * 100)
  const carrying = (place.vehicles || []).filter(v => CARRIES.includes(v))

  return (
    <div className={`tmap__row ${place.uncovered ? 'uncovered' : ''}`}>
      <span className="tmap__label">
        {place.community}
        <small>
          {place.patients} {place.patients === 1 ? 'woman' : 'women'}
          {place.road_condition && (
            <> · <span className={place.road_condition === 'poor' ? 'rough' : ''}>
              {place.road_condition} road
            </span></>
          )}
        </small>
      </span>

      <div className={`tmap__track ${place.road_condition === 'poor' ? 'rough' : ''}`}>
        {at === null ? (
          <span className="tmap__unknown">Distance not recorded</span>
        ) : (
          <span className="tmap__marker" style={{ left: `${at}%` }}>
            <span className="tmap__dot" />
            {/* Centred over the dot, except at the ends. The furthest village
                sits at 100% by definition, and a centred label there hung off
                the track — on a phone it read "140 mi". */}
            <span className="tmap__min" style={{
              transform: at > 88 ? 'translateX(-100%)'
                       : at < 8 ? 'none' : 'translateX(-50%)',
            }}>
              {minutes} min
            </span>
          </span>
        )}
      </div>

      <span className="tmap__count">
        {carrying.length === 0 ? (
          <span className="pill high">No vehicle</span>
        ) : (
          <span className="tmap__vehicles">
            {carrying.map(v => VEHICLE_LABEL[v] || v).join(' · ')}
            {place.on_a_run > 0 && <small>{place.on_a_run} on a run</small>}
          </span>
        )}
      </span>
    </div>
  )
}

/* ------------------------------------------------------------ the roster */

function Roster({ drivers, onChange }) {
  if (!drivers.length) {
    return (
      <Empty title="Nobody is registered">
        Until a driver is on this list, an emergency has nowhere to go but a
        manual phone call.
      </Empty>
    )
  }

  const places = []
  for (const d of drivers) {
    let group = places.find(p => p.name === d.community)
    if (!group) { group = { name: d.community, drivers: [] }; places.push(group) }
    group.drivers.push(d)
  }
  places.sort((a, b) => a.name.localeCompare(b.name))

  return places.map(place => (
    <div className="card" key={place.name}>
      <div className="card-head">
        <I.Pin size={17} />
        <h2>{place.name}</h2>
      </div>
      <table className="table roster">
        {/* Fixed, so the columns line up between one community's card and the
            next. Auto layout sized each table to its own longest name and the
            roster read as three unrelated tables stacked up. */}
        <colgroup>
          <col /><col style={{ width: '15%' }} /><col style={{ width: '13%' }} />
          <col style={{ width: '20%' }} /><col style={{ width: '15%' }} />
        </colgroup>
        <thead>
          <tr>
            <th>Driver</th>
            <th>Vehicle</th>
            <th>Answers</th>
            <th>Call</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {place.drivers.map(d => (
            <DriverRow key={d.id} driver={d} onChange={onChange} />
          ))}
        </tbody>
      </table>
    </div>
  ))
}

function DriverRow({ driver, onChange }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function toggle() {
    setBusy(true); setError(null)
    try {
      await patch(`/api/drivers/${driver.id}`, { available: !driver.available })
      onChange()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <tr className={driver.available ? '' : 'retired'}>
        <td>
          <div className="who">{driver.name}</div>
          <div className="sub">
            {driver.source === 'care_circle'
              ? 'Named by a household'
              : 'Registered with the programme'}
            {driver.named_by_households > 0 &&
              ` · named by ${driver.named_by_households}`}
          </div>
        </td>
        <td>
          {VEHICLE_LABEL[driver.vehicle_type] || driver.vehicle_type}
          {!driver.carries_a_patient && (
            <div className="sub">Cannot carry a patient</div>
          )}
        </td>
        <td>
          {/* Not a rate for a man nobody has rung. The cascade ranks him
              mid-table; the screen must not print that as if it were measured. */}
          {driver.response_rate === null ? (
            <span className="muted tiny">Never rung</span>
          ) : (
            <>
              {Math.round(driver.response_rate * 100)}%
              <div className="sub">{driver.accepted_count} of {driver.offered_count}</div>
            </>
          )}
        </td>
        <td>
          {/* On a handset this dials him. That is the whole point of the
              column: the number is not a record, it is the vehicle. */}
          <a href={`tel:${driver.phone}`} className="callnum">
            <I.Phone size={15} /> {phone(driver.phone)}
          </a>
        </td>
        <td style={{ textAlign: 'right' }}>
          {driver.on_run ? (
            <span className="pill critical">On a run</span>
          ) : (
            <button className="quiet small" onClick={toggle} disabled={busy}>
              {driver.available ? 'Take off duty' : 'Put back on duty'}
            </button>
          )}
        </td>
      </tr>
      {error && (
        <tr><td colSpan={5}>
          <div className="notice bad">{error}</div>
        </td></tr>
      )}
    </>
  )
}

/* -------------------------------------------------------------- a live run */

function Run({ driver, onDone }) {
  const run = driver.on_run
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function report(e) {
    e.preventDefault()
    if (!note.trim()) return
    setBusy(true); setError(null)
    try {
      await post(`/api/drivers/dispatches/${run.dispatch_id}/location`,
                 { note: note.trim() })
      setNote('')
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ borderLeft: '6px solid var(--emergency)' }}>
      <div className="row">
        <h2 style={{ margin: 0 }}>{run.patient_name}</h2>
        <span className="spacer" />
        <span className="pill critical">
          {run.status === 'accepted' ? 'On the road' : 'Ringing'}
        </span>
      </div>
      <p className="tiny muted" style={{ margin: '4px 0 12px' }}>
        {driver.name} · {VEHICLE_LABEL[driver.vehicle_type] || driver.vehicle_type}
        {' · '}
        <a href={`tel:${driver.phone}`}>{phone(driver.phone)}</a>
        {run.community && ` · from ${run.community}`}
      </p>

      <p style={{ margin: '0 0 10px' }}>
        {run.location_note
          ? <>Last reported <strong>{run.location_note}</strong>, {ago(run.location_at)}</>
          : <span className="muted">Nobody has asked him where he is yet.</span>}
      </p>

      {/* Typed by a person, because his handset cannot report a position.
          Nothing here is automatic and the screen should not imply it is. */}
      <form className="row" onSubmit={report}>
        <input className="field" value={note} style={{ marginBottom: 0 }}
               onChange={e => setNote(e.target.value)}
               placeholder="Where did he say he was?" maxLength={200} />
        <button className="primary" disabled={busy || !note.trim()}
                style={{ flex: '0 0 auto', whiteSpace: 'nowrap' }}>
          {busy ? 'Saving…' : 'Record it'}
        </button>
      </form>
      <p className="tiny muted" style={{ marginTop: 8 }}>
        As he said it on the phone. There is no tracking on his handset.
      </p>
      {error && <div className="notice bad">{error}</div>}
    </div>
  )
}

/* ---------------------------------------------------------------- adding */

function AddDriver({ communities, onDone }) {
  // The coverage list arrives worst-first, so the form opens pointed at the
  // village with women in it and nothing that can carry them. That is the one
  // this button is nearly always being pressed for.
  const [form, setForm] = useState({
    name: '', phone: '', community: communities[0] || '',
    vehicle_type: 'motorking',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await post('/api/drivers', form)
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Register a driver</h2>

      <label htmlFor="d-name">Name</label>
      <input id="d-name" className="field" value={form.name}
             onChange={set('name')} required maxLength={120} />

      <label htmlFor="d-phone">Phone</label>
      <input id="d-phone" className="field" value={form.phone} type="tel"
             onChange={set('phone')} required placeholder="024 000 0000" />
      <p className="tiny muted" style={{ marginTop: -6 }}>
        This is the number the platform will ring during an emergency. If it
        cannot be dialled it will be refused here rather than at two in the
        morning.
      </p>

      <label htmlFor="d-community">Community</label>
      <input id="d-community" className="field" value={form.community}
             onChange={set('community')} required list="communities"
             placeholder="The village he lives in" />
      <datalist id="communities">
        {communities.map(c => <option key={c} value={c} />)}
      </datalist>
      <p className="tiny muted" style={{ marginTop: -6 }}>
        Where he lives, not where he drives. Her own community is rung first,
        and the queue carries on into the next village rather than stopping.
      </p>

      <label htmlFor="d-vehicle">Vehicle</label>
      <select id="d-vehicle" className="field" value={form.vehicle_type}
              onChange={set('vehicle_type')}>
        {Object.entries(VEHICLE_LABEL).map(([value, label]) => (
          <option key={value} value={value}>
            {label}{CARRIES.includes(value) ? '' : ' — cannot carry a patient'}
          </option>
        ))}
      </select>

      {error && <div className="notice bad">{error}</div>}

      <button className="primary wide" disabled={busy}>
        {busy ? 'Registering…' : 'Add him to the roster'}
      </button>
    </form>
  )
}
