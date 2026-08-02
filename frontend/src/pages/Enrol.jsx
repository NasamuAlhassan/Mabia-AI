import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { post } from '../api'
import { outbox, uuid7 } from '../db'

// Enrolment happens in a compound, often with no signal. So the id is generated
// here, on the device: if this has to be queued and retried, the server
// de-duplicates on that id and one woman is enrolled once.

const TABOOS = [
  ['eggs', 'Eggs'], ['goat', 'Goat meat'], ['guinea_fowl', 'Guinea fowl'],
  ['fresh_fish', 'Fresh fish'], ['milk_fresh', 'Fresh milk'],
]

export default function Enrol() {
  const navigate = useNavigate()
  const [f, setF] = useState({
    name: '', phone: '', secondary_phone: '', language: 'dagbani',
    community: 'Kpale', region: 'Northern', edd: '', affordability: 'low',
  })
  const [taboos, setTaboos] = useState([])
  const [consent, setConsent] = useState(false)
  const [flash, setFlash] = useState(null)
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    if (!consent) { setFlash({ bad: true, text: 'Consent must be recorded first.' }); return }
    setBusy(true); setFlash(null)
    const event_id = uuid7()
    const body = { ...f, taboos, consent: true, event_id, edd: f.edd || null }
    try {
      const created = await post('/api/patients', body)
      navigate(`/patients/${created.id}`)
    } catch (err) {
      await outbox.add({
        event_id, event_type: 'enrolment', payload: body,
        occurred_at: new Date().toISOString(),
      })
      setFlash({ warn: true, text: 'No signal — enrolment queued on this device and will sync.' })
    } finally { setBusy(false) }
  }

  return (
    <>
      <h1>Enrol a household</h1>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="n">Name</label>
          <input id="n" required value={f.name} onChange={set('name')} />
        </div>
        <div className="field">
          <label htmlFor="p">Phone</label>
          <input id="p" required inputMode="tel" value={f.phone}
                 onChange={set('phone')} placeholder="+233…" />
        </div>
        <div className="field">
          <label htmlFor="s">Second household contact</label>
          <input id="s" inputMode="tel" value={f.secondary_phone}
                 onChange={set('secondary_phone')} />
          <div className="help">Tried when she cannot be reached, before a physical visit.</div>
        </div>
        <div className="row wrap" style={{ gap: '.6rem' }}>
          <div className="field" style={{ flex: 1, minWidth: 140 }}>
            <label htmlFor="l">Language</label>
            <select id="l" value={f.language} onChange={set('language')}>
              {['dagbani', 'kusaal', 'frafra', 'gonja', 'english'].map(x =>
                <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 140 }}>
            <label htmlFor="c">Community</label>
            <input id="c" required value={f.community} onChange={set('community')} />
          </div>
        </div>
        <div className="row wrap" style={{ gap: '.6rem' }}>
          <div className="field" style={{ flex: 1, minWidth: 140 }}>
            <label htmlFor="r">Region</label>
            <select id="r" value={f.region} onChange={set('region')}>
              {['Northern', 'North East', 'Savannah', 'Upper East', 'Upper West']
                .map(x => <option key={x} value={x}>{x}</option>)}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 140 }}>
            <label htmlFor="e">Due date</label>
            <input id="e" type="date" value={f.edd} onChange={set('edd')} />
            <div className="help">Builds the WHO eight-contact schedule.</div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="a">What the household can afford</label>
          <select id="a" value={f.affordability} onChange={set('affordability')}>
            <option value="low">Low — free and cheap foods only</option>
            <option value="medium">Medium — can buy eggs, fish, milk sometimes</option>
          </select>
          <div className="help">Nutrition advice is filtered by this. Advice she cannot follow is not advice.</div>
        </div>
        <div className="field">
          <label>Foods she will not eat</label>
          <div className="chips">
            {TABOOS.map(([k, l]) => (
              <button type="button" key={k}
                      className={`chip ${taboos.includes(k) ? 'on' : ''}`}
                      onClick={() => setTaboos(t =>
                        t.includes(k) ? t.filter(x => x !== k) : [...t, k])}>{l}</button>
            ))}
          </div>
          <div className="help">
            The platform does not argue with a taboo on an automated call. It
            offers another food in the same group.
          </div>
        </div>
        <div className="field">
          <label className="row" style={{ gap: '.5rem', alignItems: 'flex-start' }}>
            <input type="checkbox" checked={consent} style={{ width: 22, minHeight: 22 }}
                   onChange={e => setConsent(e.target.checked)} />
            <span style={{ fontWeight: 400, fontSize: '.9rem' }}>
              She consents to scheduled calls, to her health information being
              stored, and to a second household contact being called if she
              cannot be reached.
            </span>
          </label>
        </div>
        {flash && <div className={`notice ${flash.bad ? 'bad' : 'warn'}`}>{flash.text}</div>}
        <button className="primary wide" disabled={busy}>
          {busy ? <span className="spin" /> : 'Enrol'}
        </button>
      </form>
    </>
  )
}
