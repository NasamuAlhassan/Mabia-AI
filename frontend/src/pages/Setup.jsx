import { useEffect, useState } from 'react'
import { get, post, put } from '../api'

// The screen that turns this from a demo into something that rings a real
// handset. Everything Africa's Talking needs goes in here, and the two test
// buttons prove the whole chain end to end rather than claiming it works.

const GROUPS = [
  {
    title: 'Provider',
    blurb: 'The simulator needs no account and runs every flow on screen. ' +
           'Switch to Africa’s Talking when your credentials are in.',
    keys: ['telephony_provider', 'at_environment'],
  },
  {
    title: 'Africa’s Talking credentials',
    blurb: 'From your dashboard. The API key is masked once saved — to ' +
           'change it, type a new one.',
    keys: ['at_username', 'at_api_key'],
  },
  {
    title: 'Numbers',
    blurb: 'The voice number places calls. The hotline number is the one ' +
           'caregivers ring and hang up on, so the platform can call them back.',
    keys: ['at_voice_number', 'at_sender_id', 'at_ussd_code', 'hotline_number'],
  },
  {
    title: 'Callbacks and testing',
    blurb: 'Africa’s Talking asks your server what to play, over HTTPS. ' +
           'Without a public URL a call connects and then falls silent.',
    keys: ['public_base_url', 'test_phone', 'default_language'],
  },
]

const OPTIONS = {
  telephony_provider: [
    ['simulator', 'Simulator — no account needed'],
    ['africastalking', 'Africa’s Talking — real calls'],
  ],
  at_environment: [['sandbox', 'Sandbox'], ['live', 'Live']],
  default_language: [
    ['dagbani', 'Dagbani'], ['kusaal', 'Kusaal'], ['frafra', 'Frafra'],
    ['gonja', 'Gonja'], ['english', 'English'],
  ],
}

export default function Setup() {
  const [fields, setFields] = useState([])
  const [readiness, setReadiness] = useState(null)
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState(null)

  async function load() {
    const data = await get('/api/setup')
    setFields(data.fields)
    setReadiness(data.readiness)
    const next = {}
    data.fields.forEach(f => { next[f.key] = f.value })
    setValues(next)
  }

  useEffect(() => { load().catch(e => setFlash({ bad: true, text: e.message })) }, [])

  const byKey = Object.fromEntries(fields.map(f => [f.key, f]))

  async function save() {
    setBusy(true); setFlash(null)
    try {
      const data = await put('/api/setup', { values })
      setFields(data.fields); setReadiness(data.readiness)
      setFlash({ text: 'Saved.' })
    } catch (e) {
      setFlash({ bad: true, text: e.message })
    } finally { setBusy(false) }
  }

  async function runTest(kind) {
    setBusy(true); setFlash(null)
    try {
      const out = await post(`/api/setup/test-${kind}`)
      setFlash(out.ok
        ? { text: `${kind === 'call' ? 'Call placed' : 'Message sent'}. ${out.hint || ''}` }
        : { bad: true, text: out.error || 'Failed.' })
    } catch (e) {
      setFlash({ bad: true, text: e.message })
    } finally { setBusy(false) }
  }

  const live = values.telephony_provider === 'africastalking'

  return (
    <>
      <h1>Setup</h1>
      <p className="muted">
        Fill this in and the platform will call a real handset. Leave it on the
        simulator and everything still works on screen.
      </p>

      {flash && (
        <div className={`notice ${flash.bad ? 'bad' : 'ok'}`}>{flash.text}</div>
      )}

      {readiness && (
        <div className="card">
          <div className="card-head">
            <h2>What works right now</h2>
            <span className="spacer" />
            <span className={`badge ${readiness.can_call ? 'green' : 'amber'}`}>
              {readiness.can_call ? 'Can call' : 'Cannot call yet'}
            </span>
          </div>
          {readiness.checks.map(c => (
            <div className="check" key={c.name}>
              <span className="dot">{c.ok ? '✓' : '✗'}</span>
              <span><strong>{c.name}</strong> — <span className="muted">{c.detail}</span></span>
            </div>
          ))}
          {readiness.live && (
            <div className="notice warn" style={{ marginTop: '.6rem' }}>
              Live mode. Calls and messages will reach real handsets and cost real
              airtime.
            </div>
          )}
        </div>
      )}

      {GROUPS.map(group => (
        <div className="card" key={group.title}>
          <h2>{group.title}</h2>
          <p className="muted tiny">{group.blurb}</p>
          {group.keys.filter(k => byKey[k]).map(key => {
            const field = byKey[key]
            const opts = OPTIONS[key]
            return (
              <div className="field" key={key}>
                <label htmlFor={key}>{field.label}</label>
                {opts ? (
                  <select id={key} value={values[key] ?? ''}
                          onChange={e => setValues({ ...values, [key]: e.target.value })}>
                    {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                ) : (
                  <input id={key}
                         type={field.secret ? 'password' : 'text'}
                         inputMode={key.includes('phone') || key.includes('number')
                                    ? 'tel' : 'text'}
                         placeholder={field.secret && field.configured ? '••••••••' : ''}
                         value={values[key] ?? ''}
                         onChange={e => setValues({ ...values, [key]: e.target.value })} />
                )}
                <div className="help">{field.help}</div>
              </div>
            )
          })}
        </div>
      ))}

      <div className="card">
        <button className="primary wide" onClick={save} disabled={busy}>
          {busy ? <span className="spin" /> : 'Save settings'}
        </button>
      </div>

      <div className="card">
        <h2>Test it</h2>
        <p className="muted tiny">
          The fifteen-minute check. If a real handset rings, the whole IVR risk
          collapses to recording the audio.
        </p>
        <div className="stack">
          <button className="wide" onClick={() => runTest('call')} disabled={busy}>
            ☎ Place a test call to {values.test_phone || 'your number'}
          </button>
          <button className="wide" onClick={() => runTest('sms')} disabled={busy}>
            ✉ Send a test message
          </button>
        </div>
        {!live && (
          <div className="notice info" style={{ marginTop: '.7rem' }}>
            On the simulator these appear on the <strong>Calls</strong> tab
            instead of a handset.
          </div>
        )}
      </div>

      <div className="card tight">
        <div className="tiny muted">
          <strong>Local testing.</strong> Africa’s Talking has to reach your
          server over HTTPS. Run <code>ngrok http 8000</code> and paste the
          https URL into <em>Public callback URL</em>, then set the same URL as
          the callback on your voice number in the Africa’s Talking dashboard.
        </div>
      </div>
    </>
  )
}
