import { Link, useNavigate } from 'react-router-dom'
import { useData, Failed, Skeleton, ago } from '../lib/data'
import CriticalAction from '../lib/CriticalAction'
import { display as phone } from '../phone'
import * as I from '../components/Icons'

// The day, in the order it should be worked.
//
// Sections are numbered because a worker and her supervisor need to refer to
// the same thing out loud over a bad line -- "look at two" is faster and less
// ambiguous than "the tasks card". Urgency is carried by ink coverage and
// position first and colour second, so the triage survives greyscale, a bad
// projector, and a red-green colour-blind judge.

const REASONS = {
  'sign.bleeding': 'Severe vaginal bleeding',
  'sign.convulsions': 'Convulsions or fits',
  'sign.severe_headache': 'Severe headache, blurred vision',
  'sign.reduced_fetal_movement': 'Baby moving much less',
  'sign.water_broken': 'Waters broken without labour',
  'sign.severe_abdominal_pain': 'Severe abdominal pain',
  'sign.difficulty_breathing': 'Difficulty breathing',
  'sign.unconscious': 'Loss of consciousness',
  'sign.fever': 'Fever',
  'sign.swelling': 'Swollen face and hands',
  'sign.severe_vomiting': 'Persistent vomiting',
  'muac.mother_low': 'Her arm measure is low',
  'muac.child_moderate': 'Child’s arm measure is low',
  'muac.child_severe': 'Child severely malnourished',
  'diet.persistently_low': 'Poor diet twice running',
  'ifa.not_adherent': 'Not taking iron tablets',
  'contact.unreachable': 'No answer three times',
  'access.remote': 'Far from care on a poor road',
  'access.unknown': 'Distance to care not recorded',
  'access.slow': 'A long way from care',
  'emergency.open': 'Emergency still open',
  'hotline.nurse_unreachable': 'Could not reach a nurse',
  'call.hotline_unfinished': 'Rang the hotline, no answers taken',
  'call.hotline_unfinished_shared_phone':
    'Someone on this shared phone rang the hotline',
}

export const reasonLabel = (code) => REASONS[code] || code

const RISK_PILL = { red: 'high', amber: 'medium', green: 'low' }
const RISK_WORD = { red: 'HIGH', amber: 'MEDIUM', green: 'LOW' }

export default function Dashboard() {
  const navigate = useNavigate()
  const list = useData('/api/worklist', { interval: 20000 })
  const emergencies = useData('/api/emergencies', { interval: 20000 })
  const contacts = useData('/api/contacts/due', { interval: 60000 })
  const metrics = useData('/api/metrics', { interval: 120000 })

  if (list.loading && !list.data) return <Skeleton rows={5} />
  if (!list.data) return <Failed error={list.error} onRetry={list.reload} />

  const patients = list.data.patients || []
  const high = patients.filter(p => p.risk_level === 'red')
  const open = (emergencies.data || []).filter(
    e => e.status === 'pending_validation')
  const due = contacts.data?.due || []

  return (
    <>
      {/* 1. Whoever must be seen first, taking the top of the screen. */}
      <div className="card">
        <div className={`card-head ${high.length ? 'alarm' : ''}`}>
          <I.People size={16} />
          1. High-risk patients
          <span className="spacer" />
          <span className={`count-badge ${high.length ? '' : 'quiet'}`}>
            {high.length}
          </span>
        </div>
        {high.length === 0 ? (
          <div className="card-body muted tiny">
            Nobody is at high risk right now. That is the result, not an empty
            screen — it means every red case has been closed by a human.
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th><th>Risk level</th><th>Reason</th>
                <th>Distance</th><th />
              </tr>
            </thead>
            <tbody>
              {high.map(p => (
                <tr key={p.id} className="clickable"
                    onClick={() => navigate(`/patients/${p.id}`)}>
                  <td className="who">{p.name}</td>
                  <td><span className="pill high">HIGH</span></td>
                  <td>{(p.reason_codes || []).map(reasonLabel).join(', ')
                       || 'Danger signs reported'}</td>
                  <td>{p.minutes_to_facility != null
                        ? `${p.minutes_to_facility} min away`
                        : <span className="muted">Not recorded</span>}</td>
                  <td className="chev"><I.Chevron /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid g3" style={{ marginTop: 16 }}>
        {/* 2. Today */}
        <div className="card">
          <div className="card-head">
            <I.Calendar size={16} /> 2. Today’s tasks
          </div>
          <div className="card-body">
            <div className="taskgroup">
              Scheduled visits <span className="count-badge quiet">{due.length}</span>
            </div>
            {due.length === 0 && (
              <div className="muted tiny">Nothing due today.</div>
            )}
            <div className="tasklist">
              {due.slice(0, 6).map(c => (
                <div className="taskrow" key={c.contact_id}>
                  <span className="when">
                    {c.due_date ? new Date(c.due_date).toLocaleDateString(
                      undefined, { day: '2-digit', month: 'short' }) : '—'}
                  </span>
                  <span>
                    <span className="what">{c.name}</span>
                    <span className="why" style={{ display: 'block' }}>
                      {c.community} · antenatal contact, week {c.week}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="card-foot">
            <Link to="/visits">View full schedule →</Link>
          </div>
        </div>

        {/* 3. Emergencies waiting on a human */}
        <div className="card">
          <div className={`card-head ${open.length ? 'alarm' : ''}`}>
            <I.Radio size={16} /> 3. Incoming emergencies
            <span className="spacer" />
            <span className={`count-badge ${open.length ? '' : 'quiet'}`}>
              {open.length}
            </span>
          </div>
          <div className="card-body">
            {open.length === 0 && (
              <div className="muted tiny">
                Nothing waiting for you. An emergency appears here the moment a
                danger sign is reported, and stays until you confirm it.
              </div>
            )}
            {open.map(em => (
              <div className="emcard" key={em.id}>
                <div className="top">
                  <span className="at">{ago(em.created_at)}</span>
                  <span className="who">{em.patient?.name}</span>
                  <span className="spacer" />
                  <span className="pill high">HIGH RISK</span>
                </div>
                <div className="what">
                  {(em.reasons || []).map(reasonLabel).join(', ')
                   || 'Danger signs reported'}
                </div>
                <div className="far">
                  {em.patient?.community}
                  {em.patient?.phone ? ` · ${phone(em.patient.phone)}` : ''}
                </div>
                {em.alert_failed && (
                  <div className="notice bad tiny" style={{ marginBottom: 10 }}>
                    The text message to her health worker did not send. Reach
                    her another way.
                  </div>
                )}
                <div className="acts">
                  <CriticalAction
                    path={`/api/emergencies/${em.id}/validate`}
                    label="Respond"
                    busyLabel="Calling…"
                    doneLabel="Driver called"
                    className="danger"
                    holdMs={700}
                    holdHint={false}
                    onDone={() => { emergencies.reload(); list.reload() }} />
                  <button onClick={() => navigate(`/patients/${em.patient?.id}`)}>
                    Assign driver
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="card-foot">
            <Link to="/visits/facility">View all emergencies →</Link>
          </div>
        </div>

        {/* 4. The things she starts rather than responds to */}
        <div className="card">
          <div className="card-head">
            <I.Bolt size={16} /> 4. Quick actions
          </div>
          <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
            <button className="quickrow" onClick={() => navigate('/patients')}>
              <span className="ic red"><I.Warning size={18} /></span>
              <span>
                <span className="t" style={{ display: 'block' }}>Trigger emergency</span>
                <span className="s">Open a patient and confirm a danger sign</span>
              </span>
              <span className="chev"><I.Chevron /></span>
            </button>
            <button className="quickrow" onClick={() => navigate('/visits/enrol')}>
              <span className="ic green"><I.AddPerson size={18} /></span>
              <span>
                <span className="t" style={{ display: 'block' }}>Add patient</span>
                <span className="s">Register a new household</span>
              </span>
              <span className="chev"><I.Chevron /></span>
            </button>
            <button className="quickrow" onClick={() => navigate('/patients')}>
              <span className="ic green"><I.People size={18} /></span>
              <span>
                <span className="t" style={{ display: 'block' }}>View all patients</span>
                <span className="s">See every registered woman</span>
              </span>
              <span className="chev"><I.Chevron /></span>
            </button>
          </div>
        </div>
      </div>

      {/* 5. What the machine itself is doing */}
      <div className="grid g2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-head"><I.Info size={16} /> 5. System information</div>
          <div className="card-body">
            <div className="factgrid">
              <div className="fact">
                <div className="k">Women enrolled</div>
                <div className="v">{metrics.data?.enrolled ?? '—'}</div>
              </div>
              <div className="fact">
                <div className="k">Reached on schedule</div>
                <div className="v">
                  {metrics.data?.reach_rate != null
                    ? `${metrics.data.reach_rate}%` : '—'}
                </div>
              </div>
              <div className="fact">
                <div className="k">Emergencies open</div>
                <div className="v">{(emergencies.data || []).length}</div>
              </div>
              <div className="fact">
                <div className="k">Data connection</div>
                <div className="v" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <I.Signal /> {navigator.onLine ? 'Good' : 'None'}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><I.Help size={16} /> Need help?</div>
          <div className="card-body tiny muted">
            Every red case waits for a person. If a driver cannot be reached the
            system tells you rather than closing the case, and nothing here
            decides anything on its own — it sorts, and you decide.
          </div>
        </div>
      </div>
    </>
  )
}
