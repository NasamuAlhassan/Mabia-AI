import { useEffect, useState } from 'react'
import { get, post } from '../api'

// The same webhook a real handset drives, reached from a browser. Nothing here
// is a mock of the IVR -- it is the IVR.

export default function Simulator() {
  const [handsets, setHandsets] = useState([])
  const [messages, setMessages] = useState([])
  const [active, setActive] = useState(null)
  const [screen, setScreen] = useState('')
  const [ended, setEnded] = useState(false)

  async function load() {
    try {
      setHandsets((await get('/api/simulator/handsets')).handsets)
      setMessages((await get('/api/simulator/messages')).messages)
    } catch {}
  }
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t) }, [])

  const [pressing, setPressing] = useState(false)
  const [native, setNative] = useState('')
  const [error, setError] = useState('')

  async function press(sessionId, digit) {
    // Guarded: double-tapping the keypad on a slow link used to fire two
    // presses into the same IVR session and walk the state machine twice.
    if (pressing) return
    setPressing(true); setError('')
    try {
      const out = await post('/api/simulator/press',
                             { session_id: sessionId, digit })
      setActive(sessionId)
      setScreen(out.spoken || '(silence)')
      setNative(out.in_language || '')
      setEnded(out.ended)
      load()
    } catch (e) {
      setError(e.message === 'offline'
        ? 'No connection to the server.' : e.message)
    } finally { setPressing(false) }
  }

  return (
    <>
      <h1>Calls</h1>
      <p className="muted">
        Answer a ringing handset and press keys. This drives the real call flow,
        so it works with no telephony account and no signal.
      </p>

      <div className="card">
        <div className="row">
          <h2 style={{ margin: 0 }}>Ringing</h2>
          <span className="spacer" />
          <button className="small" onClick={async () => {
            await post('/api/telephony/run-callbacks'); load()
          }}>Run call-backs</button>
        </div>
        {handsets.length === 0 && (
          <p className="muted tiny">
            Nothing ringing. Confirm an emergency on the Worklist, or place a
            test call from Setup.
          </p>
        )}
        {handsets.map(h => (
          <div className={`handset ${h.ringing ? 'ringing' : ''}`} key={h.session_id}
               style={{ marginTop: '.7rem' }}>
            <div className="row">
              <strong>{h.who}</strong>
              <span className="spacer" />
              <span className="badge plain">{h.purpose}</span>
            </div>
            <div className="muted tiny" style={{ marginBottom: '.5rem' }}>
              {h.phone} · {h.language}
            </div>
            <div className="screen" role="status" aria-live="polite">
              {active === h.session_id ? screen
                : h.ringing ? 'Ringing… press Answer' : 'In progress'}
              {active === h.session_id && native && (
                <span className="native">
                  {native}
                  <span className="muted tiny" style={{ display: 'block' }}>
                    what she would hear, in {h.language} — translated by Khaya
                  </span>
                </span>
              )}
            </div>
            {error && <div className="notice bad" role="alert">{error}</div>}
            {active === h.session_id && ended ? (
              <div className="notice ok">Call ended.</div>
            ) : (
              <>
                {h.ringing && (
                  <button className="primary wide" style={{ marginBottom: '.5rem' }}
                          onClick={() => press(h.session_id, null)}>Answer</button>
                )}
                <div className="keypad">
                  {['1', '2', '3', '7', '9', '0'].map(d => (
                    <button key={d} disabled={pressing}
                            onClick={() => press(h.session_id, d)}>{d}</button>
                  ))}
                </div>
                <p className="tiny muted" style={{ marginTop: '.5rem' }}>
                  1 = yes · 2 = no · 9 = speak to a nurse, from any point.
                  Try 3, 7 or 0 — a wrong key re-asks rather than being recorded
                  as a denial.
                </p>
              </>
            )}
          </div>
        ))}
      </div>

      <div className="card">
        <h2>Messages sent</h2>
        <p className="muted tiny">Every SMS the platform pushed, and to whom.</p>
        {messages.length === 0 && <p className="muted tiny">Nothing yet.</p>}
        {messages.map(m => (
          <div className="sms" key={m.id}>
            <div className="row">
              <strong className="tiny">{m.to}</strong>
              <span className="spacer" />
              <span className={`badge ${m.status === 'sent' ? 'green' : 'red'}`}>
                {m.kind}
              </span>
            </div>
            <div>{m.body}</div>
            {m.error && <div className="tiny" style={{ color: 'var(--red)' }}>{m.error}</div>}
          </div>
        ))}
      </div>
    </>
  )
}
