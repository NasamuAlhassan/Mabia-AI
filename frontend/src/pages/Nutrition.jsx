import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'
import { useData, Empty, Failed, Skeleton } from '../lib/data'

// The nutrition officer's screen.
//
// The caseload used to be a four-column table inside a horizontal scroller on a
// 390px phone, showing one arm measurement per child with no history. Direction
// of travel is the entire clinical question in CMAM — a child at 12.2 cm on the
// way up and one at 12.2 cm on the way down are different children — and a
// single number cannot express it. So this is a trajectory list, sorted by who
// is falling fastest rather than alphabetically.

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December']
const REGIONS = ['Northern', 'North East', 'Savannah', 'Upper East', 'Upper West']

export default function Nutrition() {
  const caseload = useData('/api/worklist/nutrition', { interval: 30000 })
  const [tab, setTab] = useState('caseload')

  return (
    <>
      <h1>Nutrition</h1>

      <div className="chips" style={{ marginBottom: 16 }}>
        {[['caseload', 'Who needs attention'], ['bench', 'What we would advise']]
          .map(([key, label]) => (
            <button key={key} className="chip" aria-pressed={tab === key}
                    onClick={() => setTab(key)}>{label}</button>
          ))}
      </div>

      {tab === 'caseload' ? <Caseload state={caseload} /> : <Bench />}
    </>
  )
}

function Caseload({ state }) {
  if (state.loading && !state.data) return <Skeleton rows={4} />
  if (!state.data) return <Failed error={state.error} onRetry={state.reload} />

  const rows = state.data.patients || []
  const concerns = rows.filter(r => r.concern)
  const rest = rows.filter(r => !r.concern)

  return (
    <>
      <h2 className="band-head">
        Needs attention {concerns.length > 0 && `· ${concerns.length}`}
      </h2>
      {concerns.length === 0 ? (
        <Empty title="Nobody is falling behind">
          Every measured child and mother is above the threshold.
        </Empty>
      ) : concerns.map(r => <Trajectory key={r.id} row={r} />)}

      {rest.length > 0 && (
        <details style={{ marginTop: 24 }}>
          <summary className="disclosure" style={{ cursor: 'pointer' }}>
            {rest.length} stable
          </summary>
          {rest.map(r => <Trajectory key={r.id} row={r} />)}
        </details>
      )}
    </>
  )
}

function Trajectory({ row }) {
  const child = row.child_series || []
  const mother = row.mother_series || []
  return (
    <div className="person today" style={{ borderLeftColor: row.concern
      ? 'var(--emergency)' : 'var(--line)' }}>
      <div className="row">
        <Link className="name" to={`/patients/${row.id}`}>{row.name}</Link>
        <span className="spacer" />
        {row.mdd_score != null && (
          <span className={`badge ${row.mdd_score >= 5 ? 'green' : 'amber'}`}>
            {row.mdd_score}/{row.mdd_instrument === 'mdd_w' ? 10 : 8}
            {row.mdd_instrument === 'mdd_w' ? ' MDD-W' : ' child'}
          </span>
        )}
      </div>
      <div className="meta">{row.community}</div>

      {child.length > 0 && (
        <Series label="Child arm measure" values={child} trend={row.child_trend}
                thresholds={[11.5, 12.5]} />
      )}
      {mother.length > 0 && (
        <Series label="Her arm measure" values={mother} trend={row.mother_trend}
                thresholds={[23]} />
      )}

      {row.ifa_adherent === false && (
        <div className="why">Not taking her iron and folic acid</div>
      )}
      {(row.mdd_missing || []).length > 0 && (
        <div className="why muted tiny">
          Missing: {row.mdd_missing.slice(0, 4).join(', ')}
          {row.mdd_missing.length > 4 && ` and ${row.mdd_missing.length - 4} more`}
        </div>
      )}
    </div>
  )
}

function Series({ label, values, trend, thresholds }) {
  const low = Math.min(...thresholds, ...values) - 1
  const high = Math.max(...thresholds, ...values) + 1
  const at = (v) => `${((v - low) / (high - low)) * 100}%`
  const falling = trend != null && trend < 0

  return (
    <div style={{ margin: '10px 0' }}>
      <div className="tiny" style={{ display: 'flex', gap: 8 }}>
        <strong>{label}</strong>
        <span>{values[values.length - 1]} cm</span>
        {trend != null && (
          <span style={{ color: falling ? 'var(--emergency)' : 'var(--ok)',
                         fontWeight: 700 }}>
            {falling ? '▼' : '▲'} {Math.abs(trend)} cm
          </span>
        )}
      </div>
      {/* A spark line, drawn with plain divs: no chart library on a phone that
          has to load over 2G. */}
      <div style={{ position: 'relative', height: 26, marginTop: 4,
                    borderBottom: '1px solid var(--line)' }}
           role="img"
           aria-label={`${label}: ${values.join(' then ')} centimetres`}>
        {thresholds.map(t => (
          <div key={t} style={{ position: 'absolute', left: at(t), top: 0,
                                bottom: 0, width: 1,
                                background: 'var(--emergency)', opacity: .45 }} />
        ))}
        {values.map((v, i) => (
          <div key={i} style={{
            position: 'absolute', left: at(v), top: 4 + i * 5,
            width: 8, height: 8, borderRadius: '50%', marginLeft: -4,
            background: i === values.length - 1
              ? (v < thresholds[0] ? 'var(--emergency)' : 'var(--forest-700)')
              : 'var(--line-strong)',
          }} />
        ))}
      </div>
    </div>
  )
}

function Bench() {
  const [instruments, setInstruments] = useState(null)
  const [instrument, setInstrument] = useState('mdd_w')
  const [present, setPresent] = useState([])
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [region, setRegion] = useState('Northern')
  const [afford, setAfford] = useState('low')
  const [anaemia, setAnaemia] = useState(false)
  const [result, setResult] = useState(null)
  const [stale, setStale] = useState(null)

  useEffect(() => {
    get('/api/nutrition/instruments').then(setInstruments).catch(() => {})
  }, [])

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      post('/api/nutrition/assess', {
        instrument, present, month, region, affordability: afford,
        anaemia_focus: anaemia,
      })
        .then(r => { if (!cancelled) { setResult(r); setStale(null) } })
        .catch(e => {
          if (cancelled) return
          // Never leave last month's advice on screen looking current.
          setResult(null)
          setStale(e.message === 'offline'
            ? 'No connection — showing nothing rather than advice for the wrong month.'
            : e.message)
        })
    }, 350)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [instrument, present, month, region, afford, anaemia])

  const groups = instruments?.[instrument]?.groups || []

  return (
    <>
      <div className="card">
        <p className="muted tiny">
          Two instruments, never mixed: MDD-W is ten food groups for a woman;
          the child indicator is eight and includes breast milk.
        </p>
        <div className="field">
          <label htmlFor="i">Who is this about?</label>
          <select id="i" value={instrument}
                  onChange={e => { setInstrument(e.target.value); setPresent([]) }}>
            <option value="mdd_w">A pregnant or breastfeeding woman</option>
            <option value="mdd_child">A child aged 6–23 months</option>
          </select>
        </div>

        <label>What did she eat yesterday?</label>
        <div className="chips" style={{ marginBottom: 16 }}>
          {groups.map(g => (
            <button type="button" key={g.key} className="chip"
                    aria-pressed={present.includes(g.key)}
                    onClick={() => setPresent(p => p.includes(g.key)
                      ? p.filter(x => x !== g.key) : [...p, g.key])}>
              {g.label}
            </button>
          ))}
        </div>

        <div className="row wrap" style={{ gap: 12 }}>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="m">Month</label>
            <select id="m" value={month} onChange={e => setMonth(+e.target.value)}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="rg">Region</label>
            <select id="rg" value={region} onChange={e => setRegion(e.target.value)}>
              {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="af">What she can afford</label>
            <select id="af" value={afford} onChange={e => setAfford(e.target.value)}>
              <option value="low">Little to spare</option>
              <option value="medium">Can sometimes buy</option>
            </select>
          </div>
        </div>
        <label className="row" style={{ gap: 12 }}>
          <input type="checkbox" checked={anaemia}
                 onChange={e => setAnaemia(e.target.checked)} />
          <span style={{ fontWeight: 400 }}>She may be anaemic</span>
        </label>
      </div>

      {stale && <div className="notice bad" role="alert">{stale}</div>}

      {result && (
        <div className="card" style={{ borderLeft: '6px solid var(--ochre)' }}
             role="status">
          <div className="row">
            <h2 style={{ margin: 0 }}>
              {result.recall.score} of {result.recall.total} food groups
            </h2>
            <span className="spacer" />
            <span className={`badge ${result.recall.meets_minimum ? 'green' : 'amber'}`}>
              {result.recall.meets_minimum ? 'above the minimum' : 'below the minimum'}
            </span>
          </div>

          {result.recommendation && (
            <>
              <p style={{ fontSize: '1.15rem', marginTop: 12 }}>
                {result.recommendation.message}
              </p>
              {result.recommendation.why && (
                <p className="muted">{result.recommendation.why}</p>
              )}
              {result.recommendation.anaemia_tip && (
                <div className="notice warn">{result.recommendation.anaemia_tip}</div>
              )}
              <p className="muted tiny">{result.recommendation.hydration}</p>

              {result.recommendation.food_name && (
                <p className="muted tiny">
                  <strong>{result.recommendation.food_name}</strong>
                  {result.recommendation.local_names?.dagbani &&
                    ` (${result.recommendation.local_names.dagbani})`}
                  {' · '}{result.recommendation.reason}
                  {result.recommendation.alternatives?.length > 0 &&
                    <> · if she will not take it: {
                      result.recommendation.alternatives.join(', ')}</>}
                </p>
              )}
            </>
          )}
        </div>
      )}

      <p className="muted tiny">
        Dietary diversity is a screening measure, not a diagnosis. It tells a
        health worker where to look; it does not by itself say a woman or child
        is malnourished.
      </p>
    </>
  )
}
