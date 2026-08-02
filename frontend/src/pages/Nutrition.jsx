import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'

// The nutrition officer's view, and a live bench for the engine. Change the
// month and the advice changes -- which is the whole claim, made checkable.

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December']

export default function Nutrition() {
  const [instruments, setInstruments] = useState(null)
  const [instrument, setInstrument] = useState('mdd_w')
  const [present, setPresent] = useState([])
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [region, setRegion] = useState('Northern')
  const [afford, setAfford] = useState('low')
  const [anaemia, setAnaemia] = useState(false)
  const [result, setResult] = useState(null)
  const [caseload, setCaseload] = useState(null)

  useEffect(() => {
    get('/api/nutrition/instruments').then(setInstruments).catch(() => {})
    get('/api/worklist/nutrition').then(setCaseload).catch(() => {})
  }, [])

  useEffect(() => {
    post('/api/nutrition/assess', {
      instrument, present, month, region, affordability: afford,
      anaemia_focus: anaemia,
    }).then(setResult).catch(() => {})
  }, [instrument, present, month, region, afford, anaemia])

  const groups = instruments?.[instrument]?.groups || []

  return (
    <>
      <h1>Nutrition</h1>

      {caseload && (
        <div className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>Caseload</h2>
            <span className="spacer" />
            <span className="badge amber">{caseload.concerns} need attention</span>
          </div>
          <div className="scroll-x">
            <table className="table">
              <thead>
                <tr><th>Name</th><th>Diet</th><th>MUAC</th><th>Iron</th></tr>
              </thead>
              <tbody>
                {caseload.patients.map(p => (
                  <tr key={p.id}>
                    <td><Link to={`/patients/${p.id}`}>{p.name}</Link>
                      <div className="tiny muted">{p.community}</div></td>
                    <td>{p.mdd_score == null ? '—'
                      : `${p.mdd_score}/${p.mdd_instrument === 'mdd_w' ? 10 : 8}`}
                      <div className="tiny muted">
                        {p.mdd_instrument === 'mdd_w' ? 'MDD-W' : p.mdd_instrument ? 'child' : ''}
                      </div></td>
                    <td>{p.muac_mother ? `${p.muac_mother} cm` : '—'}
                      {p.muac_child && <div className="tiny muted">child {p.muac_child}</div>}</td>
                    <td>{p.ifa_adherent == null ? '—' : p.ifa_adherent ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h2>What would we advise?</h2>
        <p className="muted tiny">
          Two instruments, never conflated: MDD-W is ten food groups for a woman,
          the child indicator is eight and includes breast milk.
        </p>

        <div className="field">
          <label htmlFor="i">Instrument</label>
          <select id="i" value={instrument}
                  onChange={e => { setInstrument(e.target.value); setPresent([]) }}>
            <option value="mdd_w">MDD-W — pregnant or lactating woman (10 groups)</option>
            <option value="mdd_child">Child 6–23 months (8 groups)</option>
          </select>
        </div>

        <label>What was eaten yesterday</label>
        <div className="chips" style={{ marginBottom: '.9rem' }}>
          {groups.map(g => (
            <button type="button" key={g.key}
                    className={`chip ${present.includes(g.key) ? 'on' : ''}`}
                    onClick={() => setPresent(p =>
                      p.includes(g.key) ? p.filter(x => x !== g.key) : [...p, g.key])}>
              {g.label}
            </button>
          ))}
        </div>

        <div className="row wrap" style={{ gap: '.6rem' }}>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="m">Month</label>
            <select id="m" value={month} onChange={e => setMonth(+e.target.value)}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="rg">Region</label>
            <select id="rg" value={region} onChange={e => setRegion(e.target.value)}>
              {['Northern', 'North East', 'Savannah', 'Upper East', 'Upper West']
                .map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <label htmlFor="af">Affordability</label>
            <select id="af" value={afford} onChange={e => setAfford(e.target.value)}>
              <option value="low">Low</option><option value="medium">Medium</option>
            </select>
          </div>
        </div>
        <label className="row" style={{ gap: '.5rem' }}>
          <input type="checkbox" checked={anaemia} style={{ width: 22, minHeight: 22 }}
                 onChange={e => setAnaemia(e.target.checked)} />
          <span style={{ fontWeight: 400 }}>Anaemia concern</span>
        </label>
      </div>

      {result && (
        <div className="card stripe green">
          <div className="row">
            <h2 style={{ margin: 0 }}>
              {result.recall.score}/{result.recall.total}
            </h2>
            <span className="spacer" />
            <span className={`badge ${result.recall.meets_minimum ? 'green' : 'amber'}`}>
              {result.recall.meets_minimum ? 'meets minimum' : 'below minimum'}
            </span>
          </div>
          {result.recommendation && (
            <>
              <p style={{ fontSize: '1.05rem', marginTop: '.6rem' }}>
                {result.recommendation.message}
              </p>
              {result.recommendation.anaemia_tip && (
                <div className="notice info">{result.recommendation.anaemia_tip}</div>
              )}
              <div className="muted tiny">
                {result.recommendation.food_name && (
                  <>
                    <strong>{result.recommendation.food_name}</strong>
                    {result.recommendation.local_names?.dagbani &&
                      <> ({result.recommendation.local_names.dagbani})</>}
                    {' · '}{result.recommendation.tier} · {result.recommendation.source}
                    {' · '}{result.recommendation.season} season<br />
                  </>
                )}
                {result.recommendation.reason}
                {result.recommendation.alternatives?.length > 0 &&
                  <><br />If she will not take it: {result.recommendation.alternatives.join(', ')}</>}
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}
