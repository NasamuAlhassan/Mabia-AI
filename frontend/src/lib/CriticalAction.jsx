import { useEffect, useId, useRef, useState } from 'react'
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
// So this component makes these guarantees:
//   1. It always says what happened — sent, queued, or failed with a reason.
//   2. Offline it writes to the outbox instead of throwing, and says so.
//   3. It cannot be double-fired: it disables itself while in flight.
//   4. An irreversible action asks for a deliberate hold rather than a tap,
//      because the button sits under a scrolling thumb. The hold is visible (a
//      fill crosses the button), it works from the keyboard (hold Space or
//      Enter), and a tap that is too short is answered, not ignored — a press
//      that does nothing and says nothing is how someone ends up pressing it
//      six times.

const TAP_MS = 250       // shorter than this is a tap, not a hold attempt

export default function CriticalAction({
  path, body, label, busyLabel = 'Sending…', doneLabel = 'Done',
  holdHint = true,
  className = 'primary wide', onDone, queueAs = null, holdMs = 0,
  confirm = null,
}) {
  const [state, setState] = useState('idle')   // idle | busy | done | queued | failed
  const [message, setMessage] = useState('')
  const [progress, setProgress] = useState(0)
  const [tooShort, setTooShort] = useState(false)
  const frame = useRef(0)
  const started = useRef(0)
  const hintId = useId()

  useEffect(() => () => cancelAnimationFrame(frame.current), [])

  async function fire() {
    if (state === 'busy' || state === 'done') return
    if (confirm && !window.confirm(confirm)) return
    setState('busy'); setMessage('')
    try {
      const out = await post(path, body)
      setState('done')
      setMessage(`${doneLabel} · ${new Date().toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit' })}`)
      navigator.vibrate?.(60)
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

  function step(now) {
    const p = Math.min(1, (now - started.current) / holdMs)
    setProgress(p)
    if (p >= 1) { frame.current = 0; fire(); setProgress(0); return }
    frame.current = requestAnimationFrame(step)
  }

  function startHold() {
    if (frame.current || state === 'busy' || state === 'done' || state === 'queued') return
    setTooShort(false)
    started.current = performance.now()
    frame.current = requestAnimationFrame(step)
  }

  function stopHold() {
    if (!frame.current) return
    cancelAnimationFrame(frame.current)
    frame.current = 0
    const held = performance.now() - started.current
    setProgress(0)
    // Let go early: say so, rather than leaving a button that seems dead.
    if (held >= 0 && held < holdMs) setTooShort(true)
    if (held < TAP_MS) navigator.vibrate?.(20)
  }

  const holding = holdMs > 0
  const busy = state === 'busy'
  const settled = state === 'done' || state === 'queued'
  const pct = Math.round(progress * 100)

  const holdProps = holding ? {
    onPointerDown: (e) => { if (e.button === 0 || e.pointerType !== 'mouse') startHold() },
    onPointerUp: stopHold,
    onPointerLeave: stopHold,
    onPointerCancel: stopHold,
    onContextMenu: (e) => e.preventDefault(),
    onKeyDown: (e) => {
      if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startHold() }
    },
    onKeyUp: (e) => { if (e.key === ' ' || e.key === 'Enter') stopHold() },
    'aria-describedby': hintId,
  } : { onClick: fire }

  return (
    <div className="critical">
      <button
        className={`${className} ${holding ? 'holdable' : ''}`}
        disabled={busy || settled}
        aria-busy={busy || undefined}
        {...holdProps}
      >
        {holding && (
          <span className="hold-fill" aria-hidden="true"
                style={{ transform: `scaleX(${progress})` }} />
        )}
        <span className="hold-label">
          {busy && <span className="spin" />}
          {busy ? busyLabel
            : state === 'done' ? doneLabel
            : state === 'queued' ? 'Queued'
            : label}
        </span>
      </button>

      {holding && holdHint && !settled && !busy && (
        <div id={hintId} className={`hold-hint ${tooShort ? 'nudge' : ''}`}
             role={tooShort ? 'status' : undefined}>
          {progress > 0 ? `Keep holding… ${pct}%`
            : tooShort ? 'Hold until it fills'
            : 'Press and hold'}
        </div>
      )}
      {holding && !holdHint && <span id={hintId} className="sr-only">
        Press and hold, or hold Space or Enter, to confirm.
      </span>}

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
