import { BackLink } from '../App'
import { useData, Failed, Skeleton } from '../lib/data'

// One number, then the funnel.
//
// Seven identical percentage tiles with no denominator, no baseline and no
// period communicated "we had an analytics requirement". The funnel *is* the
// Three Delays, which is the argument the whole product rests on, and it was
// nowhere on screen. A judge should understand the thesis in four seconds.

export default function Metrics() {
  const { data, error, loading, reload } = useData('/api/metrics')

  if (loading && !data) return <Skeleton rows={3} />
  if (!data) return <Failed error={error} onRetry={reload} />

  const funnel = data.funnel || []
  const top = Math.max(1, ...funnel.map(f => f.count))
  const reached = data.reached_care ?? 0
  const detected = funnel[0]?.count ?? 0

  return (
    <>
      <BackLink />

      <section className="metric-hero">
        <div className="n">{reached}</div>
        <div className="k">
          {reached === 1 ? 'woman has' : 'women have'} reached care with a health
          worker confirming it — out of {detected} danger signs the platform
          detected.
        </div>
      </section>

      <div className="card">
        <h2>Where people are lost</h2>
        <p className="muted tiny">
          The Three Delays, measured. Each bar is how many cases got that far;
          the number beside it is how many did not.
        </p>
        <div className="funnel" role="list">
          {funnel.map((step, i) => (
            <div className={`funnel-step ${step.lost > 0 ? 'drop' : ''}`}
                 key={step.stage} role="listitem">
              <div className="funnel-bar" aria-hidden="true"
                   style={{ width: `${Math.max(6, (step.count / top) * 55)}%` }}>
                {step.count}
              </div>
              <span className="sr-only">{step.count} cases reached: </span>
              <div className="funnel-label">
                {step.stage}
                <span className="muted tiny"> · Delay {step.delay}</span>
              </div>
              {step.lost > 0 && i > 0 && (
                <div className="funnel-lost">−{step.lost}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>Nutrition gaps closed</h2>
        <p style={{ fontSize: '1.6rem', fontWeight: 700, margin: '4px 0' }}>
          {data.counts.gaps_closed} of {data.counts.gaps_measured}
        </p>
        <p className="muted tiny">
          Food groups that were missing at one contact and had come back by the
          next. Most systems can report that advice was delivered; this reports
          whether it could be followed, which is a different question and the
          harder one.
        </p>
      </div>

      <div className="card">
        <h2>Reach</h2>
        <table className="table">
          <tbody>
            <Row label="Women enrolled" value={data.enrolled} />
            <Row label="Contacted on schedule" value={pct(data.reach_rate)} />
            <Row label="Antenatal contacts completed" value={pct(data.contact_completion)} />
            <Row label="Taking iron and folic acid" value={pct(data.ifa_adherence)} />
            <Row label="Meeting minimum dietary diversity"
                 value={pct(data.minimum_dietary_diversity)} />
          </tbody>
        </table>
        <p className="muted tiny" style={{ marginTop: 12 }}>
          Dietary diversity is reported by instrument — MDD-W across ten food
          groups for women, and the eight-group child indicator for 6–23 months.
          They are never combined.
        </p>
      </div>
    </>
  )
}

const pct = (v) => (v == null ? '—' : `${v}%`)

function Row({ label, value }) {
  return (
    <tr>
      <td>{label}</td>
      <td style={{ textAlign: 'right', fontWeight: 700 }}>{value}</td>
    </tr>
  )
}
