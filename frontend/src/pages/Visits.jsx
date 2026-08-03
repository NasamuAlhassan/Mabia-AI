import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useData, Failed, Skeleton } from '../lib/data'
import * as I from '../components/Icons'

// The schedule, and the two things a worker starts from it.
//
// The WHO eight-contact model is the spine: every enrolled woman has eight
// dated contacts from her due date, and this is the list of them. Overdue sits
// at the top because a contact that has slipped is the one that needs a person,
// not the one due next week.

const STATUS_PILL = {
  done: 'low', pending: 'plain', missed: 'medium',
  no_consent: 'medium', not_due: 'plain',
}
const STATUS_WORD = {
  done: 'Completed', pending: 'Scheduled', missed: 'Missed',
  no_consent: 'Not consented', not_due: 'Not due',
}

export default function Visits() {
  const navigate = useNavigate()
  const due = useData('/api/contacts/due', { interval: 60000 })
  const [tab, setTab] = useState('due')

  if (due.loading && !due.data) return <Skeleton rows={6} />
  if (!due.data) return <Failed error={due.error} onRetry={due.reload} />

  const today = new Date().toISOString().slice(0, 10)
  const rows = (due.data.due || []).map(c => ({ ...c, overdue: c.due_date < today }))
  const overdue = rows.filter(c => c.overdue)
  const shown = tab === 'overdue' ? overdue : rows

  return (
    <>
      <h1>Visits</h1>
      <p className="sub">
        The eight antenatal contacts, and where each household stands in them.
      </p>

      <div className="grid g2" style={{ marginBottom: 16 }}>
        <button className="quickrow card" style={{ padding: 16 }}
                onClick={() => navigate('/visits/enrol')}>
          <span className="ic green"><I.AddPerson size={18} /></span>
          <span>
            <span className="t" style={{ display: 'block' }}>Enrol a household</span>
            <span className="s">
              Works with no signal. It saves here and syncs by itself.
            </span>
          </span>
          <span className="chev"><I.Chevron /></span>
        </button>
        <button className="quickrow card" style={{ padding: 16 }}
                onClick={() => navigate('/visits/facility')}>
          <span className="ic red"><I.Warning size={18} /></span>
          <span>
            <span className="t" style={{ display: 'block' }}>Facility board</span>
            <span className="s">Who is on the way, and confirming they arrived</span>
          </span>
          <span className="chev"><I.Chevron /></span>
        </button>
      </div>

      <div className="card">
        <div className="card-head">
          <I.Calendar size={16} /> Antenatal schedule
          <span className="spacer" />
          <span className="row" style={{ gap: 6 }}>
            <button className={`small ${tab === 'due' ? 'primary' : ''}`}
                    onClick={() => setTab('due')}>All due ({rows.length})</button>
            <button className={`small ${tab === 'overdue' ? 'primary' : ''}`}
                    onClick={() => setTab('overdue')}>Overdue ({overdue.length})</button>
          </span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="table">
            <thead>
              <tr>
                <th>Patient</th><th>Contact</th><th>Due</th><th>Status</th><th />
              </tr>
            </thead>
            <tbody>
              {shown.map(c => (
                <tr key={c.contact_id} className={c.patient_id ? 'clickable' : ''}
                    onClick={() => c.patient_id && navigate(`/patients/${c.patient_id}`)}>
                  <td>
                    <div className="who">{c.name}</div>
                    <div className="sub">{c.community}</div>
                  </td>
                  <td>Week {c.week}</td>
                  <td>
                    {c.due_date ? new Date(c.due_date).toLocaleDateString() : '—'}

                  </td>
                  <td>
                    <span className={`pill ${c.overdue ? 'medium' : 'plain'}`}>
                      {c.overdue ? 'Overdue' : 'Scheduled'}
                    </span>
                    {c.attempts > 0 && (
                      <div className="sub">{c.attempts} of 3 tried</div>
                    )}
                  </td>
                  <td className="chev"><I.Chevron /></td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan={5} className="muted tiny" style={{ padding: 22 }}>
                  Nothing due. The scheduler places these calls itself, whether
                  or not anyone has signal.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
