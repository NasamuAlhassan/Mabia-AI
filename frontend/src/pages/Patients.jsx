import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useData, Failed, Skeleton } from '../lib/data'
import { reasonLabel } from './Dashboard'
import * as I from '../components/Icons'

// Everyone on this worker's list, sorted by who needs her most.
//
// Sorted by risk and not alphabetically on purpose: a list of names in
// alphabetical order is a filing cabinet, and the point of this screen is that
// the person at the top is the person to open.

const RISK_PILL = { red: 'high', amber: 'medium', green: 'low' }
const RISK_WORD = { red: 'HIGH', amber: 'MEDIUM', green: 'LOW' }
const STATUS = { red: 'critical', amber: 'active', green: 'stable' }
const STATUS_WORD = { red: 'Critical', amber: 'Active', green: 'Stable' }
const ORDER = { red: 0, amber: 1, green: 2 }

const PAGE = 10

export default function Patients() {
  const navigate = useNavigate()
  const list = useData('/api/worklist', { interval: 30000 })
  const [query, setQuery] = useState('')
  const [level, setLevel] = useState('all')
  const [page, setPage] = useState(0)

  const rows = useMemo(() => {
    const all = (list.data?.patients || []).slice()
    all.sort((a, b) => (ORDER[a.risk_level] ?? 3) - (ORDER[b.risk_level] ?? 3)
                    || (a.name || '').localeCompare(b.name || ''))
    const needle = query.trim().toLowerCase()
    return all.filter(p =>
      (level === 'all' || p.risk_level === level) &&
      (!needle || (p.name || '').toLowerCase().includes(needle)
               || (p.community || '').toLowerCase().includes(needle)
               || (p.id || '').toLowerCase().includes(needle)))
  }, [list.data, query, level])

  if (list.loading && !list.data) return <Skeleton rows={8} />
  if (!list.data) return <Failed error={list.error} onRetry={list.reload} />

  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const here = Math.min(page, pages - 1)
  const shown = rows.slice(here * PAGE, here * PAGE + PAGE)

  return (
    <>
      <h1>Patients</h1>
      <p className="sub">View and manage every registered household.</p>

      <div className="card">
        <div className="card-body" style={{ borderBottom: '1px solid var(--line)' }}>
          <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
            <div className="topsearch" style={{ display: 'block', flex: '1 1 260px' }}>
              <I.Search />
              <input value={query} aria-label="Search patients"
                     placeholder="Search by name, village or ID…"
                     onChange={e => { setQuery(e.target.value); setPage(0) }} />
            </div>
            <select value={level} aria-label="Filter by risk level"
                    style={{ flex: '0 0 190px' }}
                    onChange={e => { setLevel(e.target.value); setPage(0) }}>
              <option value="all">All risk levels</option>
              <option value="red">High only</option>
              <option value="amber">Medium only</option>
              <option value="green">Low only</option>
            </select>
            <button onClick={() => navigate('/visits/enrol')}>
              <I.AddPerson size={16} /> Add patient
            </button>
          </div>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table className="table">
            <thead>
              <tr>
                <th>Patient name</th>
                <th>Risk level</th>
                <th>Location</th>
                <th>Weeks pregnant</th>
                <th>Last contact</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map(p => (
                <tr key={p.id} className="clickable"
                    onClick={() => navigate(`/patients/${p.id}`)}>
                  <td>
                    <div className="who">{p.name}</div>
                    <div className="sub">
                      {(p.reason_codes || []).slice(0, 1).map(reasonLabel)[0]
                       || 'No concerns recorded'}
                    </div>
                  </td>
                  <td>
                    <span className={`pill ${RISK_PILL[p.risk_level] || 'stable'}`}>
                      {RISK_WORD[p.risk_level] || '—'}
                    </span>
                  </td>
                  <td>
                    <div>{p.community || '—'}</div>
                    <div className="sub">
                      {p.minutes_to_facility != null
                        ? `${p.minutes_to_facility} min from care`
                        : 'Distance not recorded'}
                    </div>
                  </td>
                  <td>{p.weeks_pregnant != null ? `${p.weeks_pregnant} weeks` : '—'}</td>
                  <td>{p.last_contact_at
                        ? new Date(p.last_contact_at).toLocaleDateString()
                        : <span className="muted">Never</span>}</td>
                  <td>
                    <span className={`pill ${STATUS[p.risk_level] || 'stable'}`}>
                      {STATUS_WORD[p.risk_level] || '—'}
                    </span>
                  </td>
                  <td className="chev"><I.Chevron /></td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={7} className="muted tiny" style={{ padding: 22 }}>
                  Nobody matches that. Clear the search to see the whole list.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card-foot" style={{ display: 'flex', alignItems: 'center' }}>
          <span className="muted tiny">
            {rows.length === 0 ? 'No patients'
              : `Showing ${here * PAGE + 1} to ${here * PAGE + shown.length} of ${rows.length}`}
          </span>
          <span className="spacer" style={{ flex: 1 }} />
          <span className="row" style={{ gap: 6 }}>
            <button className="small" disabled={here === 0}
                    onClick={() => setPage(here - 1)} aria-label="Previous page">‹</button>
            <span className="tiny muted">{here + 1} / {pages}</span>
            <button className="small" disabled={here + 1 >= pages}
                    onClick={() => setPage(here + 1)} aria-label="Next page">›</button>
          </span>
        </div>
      </div>
    </>
  )
}
