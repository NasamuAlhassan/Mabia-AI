import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'
import * as I from '../components/Icons'

export default function Login() {
  const navigate = useNavigate()
  const [phone, setPhone] = useState(
    () => localStorage.getItem('mabia.lastPhone') || '')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPin, setShowPin] = useState(false)

  useEffect(() => { document.title = 'Sign in · Mabia AI' }, [])

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await login(phone.trim(), pin.trim())
      localStorage.setItem('mabia.lastPhone', phone.trim())
      navigate('/dashboard')
    } catch (err) {
      setError(err.message === 'offline'
        ? 'No connection. Signing in for the first time needs a network.'
        : err.message)
    } finally { setBusy(false) }
  }

  return (
    <main className="auth">
      <section className="auth-story" aria-hidden="false">
        <span className="brand">
          <span className="rail-mark"><I.Logo size={40} /></span>
          <span className="rail-name">
            Mabia AI
            <span>Care Network</span>
          </span>
        </span>
        <div>
          <div className="eyebrow">CHPS worker system</div>
          <h1>Silence is never mistaken for safety.</h1>
          <p>
            Calls pregnant women and caregivers in their own language over plain
            GSM, and puts every danger sign in front of a person who decides.
          </p>
        </div>
        <ol className="auth-steps">
          <li><b>Delay 1</b> A danger sign is reported by phone and reaches you.</li>
          <li><b>Delay 2</b> A driver is rung in turn until one accepts.</li>
          <li><b>Delay 3</b> The facility is told before she arrives.</li>
        </ol>
      </section>

      <section className="auth-form">
        <div className="auth-box">
          <span className="brand brand-m">
            <span className="rail-mark"><I.Logo size={40} /></span>
            <span className="rail-name">
              Mabia AI
              <span>Care Network</span>
            </span>
          </span>

          <h2>Sign in</h2>
          <p className="muted" style={{ margin: '0 0 22px' }}>
            Use the phone number and PIN your supervisor gave you.
          </p>

          <form className="card" onSubmit={submit}>
            <div className="card-body stack" style={{ gap: 16 }}>
              <div>
                <label htmlFor="phone">Phone number</label>
                <input id="phone" type="tel" inputMode="tel" value={phone}
                       placeholder="024 000 0001" autoComplete="username"
                       onChange={e => setPhone(e.target.value)} />
                <div className="help">
                  Type it however you write it: 024, +233, or with spaces.
                </div>
              </div>
              <div>
                <label htmlFor="pin">PIN</label>
                <div className="pin-wrap">
                  <input id="pin" type={showPin ? 'text' : 'password'} inputMode="numeric"
                         value={pin} autoComplete="current-password"
                         onChange={e => setPin(e.target.value)} />
                  <button type="button" aria-pressed={showPin}
                          aria-label={showPin ? 'Hide PIN' : 'Show PIN'}
                          onClick={() => setShowPin(v => !v)}>
                    {showPin ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>
              {error && <div className="notice bad" role="alert">{error}</div>}
              <button className="primary wide" disabled={busy} aria-busy={busy}>
                {busy ? <span className="spin" /> : 'Sign in'}
              </button>
            </div>
          </form>

          {import.meta.env.DEV && (
            <div className="card" style={{ marginTop: 14 }}>
              <div className="card-body tiny muted">
                <strong>Development only.</strong> PIN <code>1234</code>.<br />
                <code>0200000001</code> Fatima Abdulai (CHPS worker)<br />
                <code>0200000002</code> Dawuda Mardia (nutrition officer)<br />
                <code>0200000003</code> Sister Ayisha (on-call nurse)
              </div>
            </div>
          )}
        </div>
      </section>
    </main>
  )
}
