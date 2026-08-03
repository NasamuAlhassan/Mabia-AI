import { useRef, useState } from 'react'
import { ApiError, post } from '../api'
import { outbox } from '../db'

// An action that must never fail silently.
//
// The worst bug in the previous build was here: "Confirm emergency and call a
// driver" was a bare `await post()` with no try, no catch and no queue. Offline
// it threw into a void, the button did nothing visible, and the CHO tapped it
// again — while a woman was bleeding. Meanwhile the same screen carried the
// sentence "Nothing dispatches until a person confirms it. That is the gate."
//
// So this component makes three guarantees:
//   1. It always says what happened — sent, queued, or failed with a reason.
//   2. Offline it writes to the outbox instead of throwing, and says so.
//   3. It cannot be double-fired: it disables itself while in flight.
//
// Irreversible actions also require a deliberate press rather than a tap,
// because this button sits under a scrolling thumb.

export default function CriticalAction({
  path, body, label, busyLabel = 'Sending…', doneLabel = 'Done',
  holdHint = true,
  className = 'primary wide', onDone, queueAs = null, holdMs = 0,
  confirm = null,
}) {
  const [state, setState] = useState('idle')   // idle | busy | done | queued | failed
  const [message, setMessage] = useState('')
  const [held, setHeld] = useState(0)
  const holdTimer = useRef(null)

  async function fire() {
    if (state === 'busy' || state === 'done') return
    if (confirm && !window.confirm(confirm)) return
    setState('busy'); setMessage('')
    try {
      const out = await post(path, body)
      setState('done')
      setMessage(`${doneLabel} · ${new Date().toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit' })}`)
      onDone?.(out)
    } catch (e) {
      const offline = e instanceof ApiError && e.status === 0
      if (offline && queueAs) {
        await outbox.add({ ...queueAs, occurred_at: new Date().toISOString() })
        setState('queued')
        setMessage('No signal — queued on this phone. It will send by itself '
                   + 'when you have a bar.')
        onDone?.(null)
      } else {
        setState('failed')
        setMessage(offline
          ? 'No signal, and this action cannot be queued. Try again in coverage.'
          : e.message)
      }
    }
  }

  function startHold() {
    if (!holdMs) return fire()
    const started = Date.now()
    holdTimer.current = setInterval(() => {
      const progress = Math.min(1, (Date.now() - started) / holdMs)
      setHeld(progress)
      if (progress >= 1) { stopHold(); fire() }
    }, 40)
  }

  function stopHold() {
    clearInterval(holdTimer.current)
    holdTimer.current = null
    setHeld(0)
  }

  const busy = state === 'busy'
  const settled = state === 'done' || state === 'queued'

  return (
    <div>
      <button
        className={className}
        disabled={busy || settled}
        onPointerDown={holdMs ? startHold : undefined}
        onPointerUp={holdMs ? stopHold : undefined}
        onPointerLeave={holdMs ? stopHold : undefined}
        onClick={holdMs ? undefined : fire}
        style={holdMs && held ? {
          backgroundImage: `linear-gradient(to right, rgba(0,0,0,.22) ${held * 100}%, transparent ${held * 100}%)`,
        } : undefined}
      >
        {busy && <span className="spin" />}
        {busy ? busyLabel
          : state === 'done' ? doneLabel
          : state === 'queued' ? 'Queued'
          : (holdMs && holdHint) ? `${label} — press and hold` : label}
      </button>
      {message && (
        <div className={`notice ${state === 'failed' ? 'bad'
                          : state === 'queued' ? 'warn' : 'ok'}`}
             role="status" style={{ marginTop: 8, marginBottom: 0 }}>
          {message}
        </div>
      )}
    </div>
  )
}
