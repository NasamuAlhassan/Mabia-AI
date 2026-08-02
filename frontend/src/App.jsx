import { useEffect, useState } from 'react'
import {
  BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate,
} from 'react-router-dom'

import { ApiError, post, token, user as userStore } from './api'
import { flush, outbox } from './db'

import Enrol from './pages/Enrol'
import Facility from './pages/Facility'
import Login from './pages/Login'
import Metrics from './pages/Metrics'
import Nutrition from './pages/Nutrition'
import Patient from './pages/Patient'
import Setup from './pages/Setup'
import Simulator from './pages/Simulator'
import Worklist from './pages/Worklist'

const TABS = [
  { to: '/worklist', glyph: '☰', label: 'Worklist' },
  { to: '/enrol', glyph: '＋', label: 'Enrol' },
  { to: '/simulator', glyph: '☎', label: 'Calls' },
  { to: '/nutrition', glyph: '🌾', label: 'Nutrition' },
  { to: '/setup', glyph: '⚙', label: 'Setup' },
]

function Shell({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const me = userStore.get()
  const [pending, setPending] = useState(0)
  const [online, setOnline] = useState(navigator.onLine)

  useEffect(() => {
    const tick = async () => setPending(await outbox.count())
    tick()
    const timer = setInterval(tick, 4000)
    const up = () => setOnline(true), down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      clearInterval(timer)
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [location.pathname])

  // Flush whenever the network comes back. Repeating a flush is safe by design.
  useEffect(() => {
    if (!online) return
    flush(post).then(r => { if (r.sent) setPending(0) }).catch(() => {})
  }, [online])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Mabia AI</span>
        <span className="spacer" />
        {!online && <span className="badge amber" title="Working offline">Offline</span>}
        {pending > 0 && (
          <span className="badge plain" title="Waiting to sync">{pending} queued</span>
        )}
        <button onClick={() => { token.clear(); navigate('/login') }}>
          {me?.name?.split(' ')[0] || 'Sign out'}
        </button>
      </header>

      <main className="main">{children}</main>

      <nav className="tabbar">
        {TABS.map(t => (
          <NavLink key={t.to} to={t.to}
                   className={({ isActive }) => isActive ? 'active' : ''}>
            <span className="glyph">{t.glyph}</span>
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

function Guard({ children }) {
  if (!token.get()) return <Navigate to="/login" replace />
  return <Shell>{children}</Shell>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Navigate to="/worklist" replace />} />
        <Route path="/worklist" element={<Guard><Worklist /></Guard>} />
        <Route path="/patients/:id" element={<Guard><Patient /></Guard>} />
        <Route path="/enrol" element={<Guard><Enrol /></Guard>} />
        <Route path="/simulator" element={<Guard><Simulator /></Guard>} />
        <Route path="/nutrition" element={<Guard><Nutrition /></Guard>} />
        <Route path="/facility" element={<Guard><Facility /></Guard>} />
        <Route path="/metrics" element={<Guard><Metrics /></Guard>} />
        <Route path="/setup" element={<Guard><Setup /></Guard>} />
        <Route path="*" element={<Navigate to="/worklist" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export { ApiError }
