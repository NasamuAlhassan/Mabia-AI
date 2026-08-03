import { useState } from 'react'
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
      <div className="auth-box">
        <div className="auth-brand">
          <span className="rail-mark"><I.Logo size={40} /></span>
          <span className="rail-name">
            Mabia AI
            <span>Care Network</span>
          </span>
        </div>
        <p className="muted tiny" style={{ textAlign: 'center', marginTop: 0 }}>
          CHPS Worker System — emergency response, voice outreach and nutrition
          coordination for Northern Ghana.
        </p>

        <form className="card" onSubmit={submit} style={{ marginTop: 20 }}>
          <div className="card-body stack">
            <div>
              <label htmlFor="phone">Phone number</label>
              <input id="phone" inputMode="tel" value={phone}
                     placeholder="024 000 0001" autoComplete="username"
                     onChange={e => setPhone(e.target.value)} />
            </div>
            <div>
              <label htmlFor="pin">PIN</label>
              <input id="pin" type="password" inputMode="numeric" value={pin}
                     autoComplete="current-password"
                     onChange={e => setPin(e.target.value)} />
            </div>
            {error && <div className="notice bad" role="alert">{error}</div>}
            <button className="primary wide" disabled={busy}>
              {busy ? <span className="spin" /> : 'Sign in'}
            </button>
            <p className="muted tiny" style={{ margin: 0, textAlign: 'center' }}>
              Type the number however you write it. 024, +233, or with spaces —
              they all reach the same account.
            </p>
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
    </main>
  )
}
