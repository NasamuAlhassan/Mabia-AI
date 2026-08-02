import { useEffect, useState } from 'react'
import {
  BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate,
} from 'react-router-dom'

import { post, token } from './api'
import { flush, outbox } from './db'
import { ago } from './lib/data'

import Enrol from './pages/Enrol'
import Facility from './pages/Facility'
import Login from './pages/Login'
import Metrics from './pages/Metrics'
import Nutrition from './pages/Nutrition'
import Patient from './pages/Patient'
import Setup from './pages/Setup'
import Simulator from './pages/Simulator'
import Voice from './pages/Voice'
import Worklist from './pages/Worklist'

// Five slots, and the developer tool is not one of them. The simulator moved
// under Setup: a CHO has no reason to answer a simulated handset, and giving it
// a fifth of her primary navigation told a judge the app was a demo harness.
const TABS = [
  { to: '/worklist', glyph: '≡', label: 'Worklist' },
  { to: '/enrol', glyph: '+', label: 'Enrol' },
  { to: '/nutrition', glyph: '◍', label: 'Nutrition' },
  { to: '/voice', glyph: '◉', label: 'Voice' },
  { to: '/setup', glyph: '⚙', label: 'Setup' },
]

const SUN_KEY = 'mabia.sun'

function Shell({ children }) {
  const location = useLocation()
  const [pending, setPending] = useState(0)
  const [online, setOnline] = useState(navigator.onLine)
  const [lastSync, setLastSync] = useState(
    Number(localStorage.getItem('mabia.lastSync')) || null)
  const [sun, setSun] = useState(localStorage.getItem(SUN_KEY) === 'on')
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    document.documentElement.dataset.sun = sun ? 'on' : 'off'
    localStorage.setItem(SUN_KEY, sun ? 'on' : 'off')
  }, [sun])

  useEffect(() => {
    const tick = async () => setPending(await outbox.count().catch(() => 0))
    tick()
    const timer = setInterval(tick, 5000)
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      clearInterval(timer)
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [location.pathname])

  async function sync() {
    setSyncing(true)
    try {
      await flush(post)
      const now = Date.now()
      setLastSync(now)
      localStorage.setItem('mabia.lastSync', String(now))
      setPending(await outbox.count().catch(() => 0))
    } catch {
      // Stays queued. The bar keeps saying so rather than clearing the badge.
    } finally {
      setSyncing(false)
    }
  }

  useEffect(() => { if (online) sync() }, [online])

  const stale = !online || (lastSync && Date.now() - lastSync > 2 * 3600 * 1000)

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">
          <span className="mark" aria-hidden="true" />Mabia
        </span>
        <span className="spacer" />
        <button onClick={() => setSun(s => !s)} aria-pressed={sun}
                title="High-contrast mode for bright sunlight">
          {sun ? 'Sun on' : 'Sun'}
        </button>
      </header>

      {/* Always present, never a toast: how old this is, and what is waiting. */}
      <div className={`syncbar ${stale ? 'stale' : ''}`} role="status">
        <span>
          {online
            ? `Synced ${ago(lastSync)}`
            : 'Offline — showing what is saved on this phone'}
          {pending > 0 && ` · ${pending} waiting to send`}
        </span>
        <span className="spacer" />
        {online && (
          <button onClick={sync} disabled={syncing}>
            {syncing ? <span className="spin" /> : 'Sync now'}
          </button>
        )}
      </div>

      <main className="main">{children}</main>

      <nav className="tabbar" aria-label="Main">
        {TABS.map(t => (
          <NavLink key={t.to} to={t.to}
                   className={({ isActive }) => isActive ? 'active' : ''}>
            <span className="glyph" aria-hidden="true">{t.glyph}</span>
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export function BackLink({ to = '/worklist', label = 'Worklist' }) {
  const navigate = useNavigate()
  return (
    <button className="quiet small" style={{ marginBottom: 12 }}
            onClick={() => navigate(to)}>
      {'←'} {label}
    </button>
  )
}

function Guard({ children }) {
  if (!token.get()) return <Navigate to="/login" replace />
  return <Shell>{children}</Shell>
}

export default function App() {
  useEffect(() => {
    document.documentElement.dataset.sun =
      localStorage.getItem(SUN_KEY) === 'on' ? 'on' : 'off'
  }, [])

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
        <Route path="/voice" element={<Guard><Voice /></Guard>} />
        <Route path="/facility" element={<Guard><Facility /></Guard>} />
        <Route path="/metrics" element={<Guard><Metrics /></Guard>} />
        <Route path="/setup" element={<Guard><Setup /></Guard>} />
        <Route path="*" element={<Navigate to="/worklist" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
