import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { token } from '../api'
import * as I from './Icons'

// The two things the header opens: what needs her attention, and who she is.
//
// The bell used to be a sync button wearing a notification badge: pressing it
// did something nobody could predict and showed nothing. And there was no way
// to sign out at all -- on a handset that is passed around a household, or lost
// in a market, that is not a missing nicety.

function usePopover() {
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    if (!open) return
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const esc = (e) => {
      if (e.key === 'Escape') {
        setOpen(false)
        box.current?.querySelector('[aria-expanded]')?.focus()
      }
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])
  return { open, setOpen, box }
}

export function AttentionMenu({ emergencies, pending, refused, syncing, online, onSync }) {
  const { open, setOpen, box } = usePopover()
  const total = emergencies.length + pending + refused.length

  return (
    <div className="menu" ref={box}>
      <button className="bell" aria-expanded={open} aria-haspopup="true"
              aria-label={total ? `${total} ${total === 1 ? 'thing needs' : 'things need'} attention`
                                : 'Notifications: nothing needs attention'}
              onClick={() => setOpen(o => !o)}>
        <I.Bell />
        {total > 0 && <span className="count">{total}</span>}
      </button>

      {open && (
        <div className="menu-panel" role="region" aria-label="Needs attention">
          <div className="menu-title">Needs attention</div>

          {total === 0 && (
            <div className="menu-empty">
              <span className="empty-ic"><I.Check size={18} /></span>
              Everything is saved and sent.
            </div>
          )}

          {emergencies.map(em => (
            <Link key={em.id} className="menu-item alarm"
                  to={em.patient?.id ? `/patients/${em.patient.id}` : '/dashboard'}
                  onClick={() => setOpen(false)}>
              <I.Warning size={18} />
              <span>
                <strong>{em.patient?.name || 'An emergency'}</strong>
                <small>Waiting for you to respond</small>
              </span>
              <I.Chevron />
            </Link>
          ))}

          {pending > 0 && (
            <div className="menu-item">
              <I.Cloud size={18} />
              <span>
                <strong>{pending} {pending === 1 ? 'record' : 'records'} waiting to send</strong>
                <small>{online ? 'Saved on this phone' : 'They send when you have a bar'}</small>
              </span>
              {online && (
                <button className="small" disabled={syncing} onClick={onSync}>
                  {syncing ? <span className="spin" /> : 'Send now'}
                </button>
              )}
            </div>
          )}

          {refused.length > 0 && (
            <div className="menu-item bad">
              <I.Info size={18} />
              <span>
                <strong>{refused.length} {refused.length === 1 ? 'record' : 'records'} could not be saved</strong>
                <small>Still on this phone. Details are at the top of the page.</small>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function UserMenu({ me, initials, role, sun, setSun, pending }) {
  const { open, setOpen, box } = usePopover()
  const navigate = useNavigate()
  const [asking, setAsking] = useState(false)

  useEffect(() => { if (!open) setAsking(false) }, [open])

  function signOut() {
    // The key that decrypts the outbox is never destroyed (see vault.js), so
    // nothing unsent is lost by signing out: it is still here, still sealed,
    // and goes the next time somebody signs in on this phone.
    token.clear()
    navigate('/login', { replace: true })
  }

  return (
    <div className="menu" ref={box}>
      <button className="avatar-btn" aria-expanded={open} aria-haspopup="true"
              aria-label={`Account: ${me?.name || 'signed in'}`}
              onClick={() => setOpen(o => !o)}>
        <span className="avatar">{initials || '—'}</span>
        <span className="whotext">
          <span className="n">{me?.name || 'Signed in'}</span>
          <span className="r">{role}</span>
        </span>
      </button>

      {open && (
        <div className="menu-panel" role="region" aria-label="Account">
          <div className="menu-who">
            <span className="avatar">{initials || '—'}</span>
            <span>
              <strong>{me?.name || 'Signed in'}</strong>
              <small>{role}</small>
            </span>
          </div>

          <button type="button" className="menu-switch" role="switch" aria-checked={sun}
                  onClick={() => setSun(s => !s)}>
            <span>
              <strong>Sunlight mode</strong>
              <small>Maximum contrast, for direct sun</small>
            </span>
            <span className="switch" aria-hidden="true"><i /></span>
          </button>

          {!asking ? (
            <button type="button" className="menu-out"
                    onClick={() => (pending > 0 ? setAsking(true) : signOut())}>
              Sign out
            </button>
          ) : (
            <div className="menu-confirm" role="alertdialog" aria-label="Confirm sign out">
              <p>
                <strong>{pending} {pending === 1 ? 'record has' : 'records have'} not sent yet.</strong>{' '}
                They stay on this phone, locked, and send when you next sign in.
              </p>
              <div className="row" style={{ gap: 8 }}>
                <button className="danger small" onClick={signOut}>Sign out anyway</button>
                <button className="small" autoFocus onClick={() => setAsking(false)}>Stay</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
