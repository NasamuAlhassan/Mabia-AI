import { useEffect, useState } from 'react'
import { get, put } from '../api'
import { display as phone } from '../phone'

// Who else has to be reached for her to actually leave the compound.
//
// Presented as four named roles rather than a contact list, because three of
// them map onto the Three Delays and the form should teach that while it is
// being filled in. A missing decision-maker is not a blank field; it is a
// specific way the referral fails.

const BLANK = { name: '', phone: '', detail: '', confirmed: false }

export default function CareCircle({ patientId }) {
  const [circle, setCircle] = useState(null)
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState(BLANK)
  const [error, setError] = useState('')

  const load = () => get(`/api/circle/${patientId}`).then(setCircle).catch(() => {})
  useEffect(() => { load() }, [patientId])

  async function save(role) {
    setError('')
    try {
      setCircle(await put(`/api/circle/${patientId}`, { role, ...draft }))
      setEditing(null)
      setDraft(BLANK)
    } catch (e) { setError(e.message) }
  }

  if (!circle) return null

  return (
    <div className="card">
      <div className="section-head" style={{ margin: '0 0 12px' }}>
        <span className="num" aria-hidden="true">◎</span>
        Care circle
        {circle.missing.length > 0 && (
          <span className="badge amber" style={{ marginLeft: 'auto' }}>
            {circle.missing.length} missing
          </span>
        )}
      </div>

      {circle.missing.length > 0 && (
        <p className="muted tiny">
          Missing: {circle.missing.join(', ')}. A referral that has no
          decision-maker or no driver tends to be a referral that does not
          happen.
        </p>
      )}

      {circle.unreachable?.length > 0 && (
        <p className="muted tiny">
          No phone number for {circle.unreachable.join(' or ')}. A name we
          cannot ring at two in the morning is not a plan.
        </p>
      )}

      <div className="circle-grid">
        {circle.members.map(m => (
          <div className={`circle-member ${m.name ? '' : 'missing'}`} key={m.role}>
            <div className="role">{m.label}</div>

            {editing === m.role ? (
              <div className="stack">
                <input aria-label={`${m.label} name`} placeholder="Name"
                       value={draft.name}
                       onChange={e => setDraft({ ...draft, name: e.target.value })} />
                <input aria-label={`${m.label} phone`} placeholder="Phone"
                       inputMode="tel" value={draft.phone}
                       onChange={e => setDraft({ ...draft, phone: e.target.value })} />
                <input aria-label={`${m.label} detail`}
                       placeholder={m.role === 'payer' ? 'NHIS number' : 'Relationship'}
                       value={draft.detail}
                       onChange={e => setDraft({ ...draft, detail: e.target.value })} />
                <label className="tiny check">
                  <input type="checkbox" checked={draft.confirmed}
                         onChange={e => setDraft({ ...draft,
                                                   confirmed: e.target.checked })} />
                  They have agreed to this
                </label>
                <div className="row" style={{ gap: 6 }}>
                  <button className="primary small" onClick={() => save(m.role)}
                          disabled={!draft.name.trim()}>Save</button>
                  <button className="small" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : m.name ? (
              <>
                <div className="who">
                  {m.name}
                  {m.confirmed
                    ? <span className="tick" title="Has agreed"> ✓</span>
                    : <span className="muted tiny"> · not yet asked</span>}
                </div>
                {m.detail && <div className="muted tiny">{m.detail}</div>}
                {m.phone && (
                  <div className="tiny"><a href={`tel:${m.phone}`}>{phone(m.phone)}</a></div>
                )}
                <div className="delay">{m.delay}</div>
                <button className="small quiet" style={{ marginTop: 8 }}
                        onClick={() => {
                          setDraft({ name: m.name, phone: m.phone || '',
                                     detail: m.detail || '',
                                     confirmed: !!m.confirmed })
                          setEditing(m.role)
                        }}>Change</button>
              </>
            ) : (
              <>
                <div className="muted tiny">{m.why}</div>
                <div className="delay">{m.delay}</div>
                <button className="small" style={{ marginTop: 8 }}
                        onClick={() => {
                          setDraft(BLANK)
                          setEditing(m.role)
                        }}>Add</button>
              </>
            )}
          </div>
        ))}
      </div>

      {error && <div className="notice bad" role="alert">{error}</div>}

      <p className="muted tiny" style={{ marginTop: 12 }}>
        When an emergency opens, the decision-maker and the emergency contact are
        messaged too — told what to do, never given a diagnosis. A driver already
        agreed with here is called before anyone else.
      </p>
    </div>
  )
}
