import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'

export default function Login() {
  const navigate = useNavigate()
  const [phone, setPhone] = useState('+233200000001')
  const [pin, setPin] = useState('1234')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await login(phone.trim(), pin.trim())
      navigate('/worklist')
    } catch (err) {
      setError(err.message === 'offline'
        ? 'No connection. Signing in for the first time needs a network.'
        : err.message)
    } finally { setBusy(false) }
  }

  return (
    <div className="auth">
      <h1>Mabia AI</h1>
      <p className="muted">CHPS emergency response, voice outreach and nutrition
        coordination for Northern Ghana.</p>

      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="phone">Phone number</label>
          <input id="phone" inputMode="tel" value={phone}
                 onChange={e => setPhone(e.target.value)} autoComplete="username" />
        </div>
        <div className="field">
          <label htmlFor="pin">PIN</label>
          <input id="pin" type="password" inputMode="numeric" value={pin}
                 onChange={e => setPin(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <div className="notice bad">{error}</div>}
        <button className="primary wide" disabled={busy}>
          {busy ? <span className="spin" /> : 'Sign in'}
        </button>
      </form>

      <div className="card tight">
        <div className="tiny muted">
          <strong>Demo accounts</strong> — PIN <code>1234</code> for all.<br />
          <code>+233200000001</code> Fatima Abdulai (CHO)<br />
          <code>+233200000002</code> Dawuda Mardia (nutrition officer)<br />
          <code>+233200000003</code> Sister Ayisha (nurse)
        </div>
      </div>
    </div>
  )
}
