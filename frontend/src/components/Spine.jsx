import { useData, Skeleton } from '../lib/data'

/* Her antenatal contacts, as a ruler of the model rather than a progress bar.
 *
 * The WHO 2016 schedule is a real typed sequence — 12, 20, 26, 30, 34, 36, 38
 * and 40 weeks — and it is not evenly spaced. It tightens toward term, because
 * that is when things go wrong. A row of identical dots says "eight things"
 * and hides the shape; marks laid out on the actual week axis say the thing
 * the schedule is for, which is that the last four contacts are four, two, two
 * and two weeks apart.
 *
 * Her own week sits on the same axis. What a worker is looking for here is one
 * question — has anything been missed behind where she is now — and that is a
 * spatial question, so it gets a spatial answer.
 */

const WORD = {
  done: 'Completed',
  pending: 'Not yet made',
  missed: 'Missed — three attempts',
  no_consent: 'She declined calls',
  not_due: 'Not due',
}

export default function Spine({ patientId, weeks }) {
  const { data, loading } = useData(`/api/contacts/schedule/${patientId}`)
  if (loading && !data) return <Skeleton rows={1} />

  const contacts = data?.contacts || []
  if (!contacts.length) return null

  const first = contacts[0].week
  const last = contacts[contacts.length - 1].week
  const span = Math.max(1, last - first)
  const at = (week) => ((week - first) / span) * 100

  const done = contacts.filter(c => c.status === 'done').length
  // Behind her, not made, and not going to be made unless someone acts. This
  // is the number the row exists to surface.
  const behind = contacts.filter(
    c => c.status !== 'done' && (c.overdue || c.status === 'missed')).length

  return (
    <div className="spine">
      <div className="spine__head">
        <strong>{done} of {contacts.length} contacts made</strong>
        {behind > 0 && (
          <span className="spine__behind">
            {behind} {behind === 1 ? 'is' : 'are'} overdue
          </span>
        )}
      </div>

      <div className="spine__rule">
        {/* Where she is now, on the same axis as the contacts. Drawn under the
            marks so it never obscures one. */}
        {weeks != null && weeks >= first && weeks <= last && (
          <span className="spine__now" style={{ left: `${at(weeks)}%` }}>
            <span>week {weeks}</span>
          </span>
        )}

        {contacts.map(c => (
          <span
            key={c.id}
            className={`spine__mark ${c.status}${
              c.status !== 'done' && c.overdue ? ' overdue' : ''}`}
            style={{ left: `${at(c.week)}%` }}
            title={`Week ${c.week} · ${WORD[c.status] || c.status}${
              c.overdue && c.status !== 'done' ? ' · overdue' : ''}`}
          >
            <span className="spine__week">{c.week}</span>
          </span>
        ))}
      </div>

      <p className="tiny muted spine__legend">
        Weeks 12 to 40, spaced as the schedule actually falls. Filled is made,
        ringed is overdue, hollow is still ahead of her.
      </p>
    </div>
  )
}
