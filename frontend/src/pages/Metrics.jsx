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
        <p className="muted tiny" style={{ marginBottom: 16 }}>
          The Three Delays, measured. Each bar is how many cases got that far,
          and underneath it is how many did not.
        </p>
        <div className="funnel" role="list">
          {funnel.map((step, i) => (
            <div className={`funnel-step ${step.lost > 0 ? 'drop' : ''}`}
                 key={step.stage} role="listitem">
              <div className="funnel-top">
                <span className="funnel-label">
                  {step.stage}
                  <span className="funnel-delay">Delay {step.delay}</span>
                </span>
                <span className="funnel-count">
                  <span className="sr-only">cases reached: </span>{step.count}
                </span>
              </div>
              <div className="funnel-track" aria-hidden="true">
                <div className="funnel-bar"
                     style={{ width: `${step.count ? Math.max(3, (step.count / top) * 100) : 0}%` }} />
              </div>
              {step.lost > 0 && i > 0 && (
                <div className="funnel-lost">{step.lost} did not get this far</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>Nutrition gaps closed</h2>
        <p className="bignum">
          {data.counts.gaps_closed}<span> of {data.counts.gaps_measured}</span>
        </p>
        <div className="funnel-track" style={{ margin: '0 20px 12px', width: 'auto' }} aria-hidden="true">
          <div className="funnel-bar" style={{ width: `${data.counts.gaps_measured
            ? (data.counts.gaps_closed / data.counts.gaps_measured) * 100 : 0}%` }} />
        </div>
        <p className="muted tiny">
          Food groups that were missing at one contact and had come back by the
          next. Most systems can report that advice was delivered; this reports
          whether it could be followed, which is a different question and the
          harder one.
        </p>
      </div>

      <div className="card">
        <h2>Reach</h2>
        <table className="table facts">
          <tbody>
            <Row label="Women enrolled" value={data.enrolled} />
            <Row label="Contacted on schedule" value={pct(data.reach_rate)} />
            <Row label="Antenatal contacts completed" value={pct(data.contact_completion)} />
            {data.contacts_not_permitted > 0 && (
              <Row label="Scheduled calls we may not make yet"
                   value={data.contacts_not_permitted} />
            )}
            <Row label="Taking iron and folic acid" value={pct(data.ifa_adherence)} />
            <Row label={`Women meeting MDD-W (of ${data.mdd_women_n ?? 0})`}
                 value={pct(data.mdd_women)} />
            <Row label={`Children 6–23m meeting MDD (of ${data.mdd_children_n ?? 0})`}
                 value={pct(data.mdd_children)} />
          </tbody>
        </table>
        {data.contacts_not_permitted > 0 && (
          <p className="muted tiny" style={{ marginTop: 12 }}>
            Those are contacts for women who have not yet agreed to be called.
            They are not failed calls and are kept out of the completion figure
            above — the fix is a conversation, not another dial.
          </p>
        )}

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
