import { useEffect, useState } from 'react'
import { get } from '../api'

const CARDS = [
  ['reach_rate', 'Reach rate', 'Enrolled women successfully contacted'],
  ['contact_completion', 'Contact completion', 'Against the WHO eight-contact model'],
  ['ifa_adherence', 'IFA adherence', 'Direct proxy for anaemia risk'],
  ['minimum_dietary_diversity', 'Dietary diversity', 'Meeting the WHO minimum'],
  ['nutrition_gaps_closed', 'Gaps closed', 'Missing groups filled by the next contact'],
  ['referral_closure_rate', 'Referral closure', 'Confirmed by a health worker'],
  ['care_received_rate', 'Care received', 'Proof of care, not just advice'],
]

export default function Metrics() {
  const [m, setM] = useState(null)
  useEffect(() => { get('/api/metrics').then(setM).catch(() => {}) }, [])
  if (!m) return <div className="center muted"><span className="spin" /></div>

  return (
    <>
      <h1>Impact</h1>
      <p className="muted">{m.enrolled} women enrolled.</p>
      <div className="metrics">
        {CARDS.map(([k, label, help]) => (
          <div className="metric" key={k}>
            <div className="v">{m[k] == null ? '—' : `${m[k]}%`}</div>
            <div className="k"><strong>{label}</strong><br />{help}</div>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: '1rem' }}>
        <h2>Why “gaps closed” matters</h2>
        <p className="muted tiny">
          Most systems can report that advice was delivered. This one reports
          whether a food group that was missing at one contact had come back by
          the next — which is the difference between guidance being given and
          guidance being followable. {m.counts.gaps_closed} of{' '}
          {m.counts.gaps_measured} measured gaps have closed so far.
        </p>
      </div>
    </>
  )
}
