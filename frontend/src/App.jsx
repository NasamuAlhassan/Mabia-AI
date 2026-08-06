import { useEffect, useState } from 'react'
import {
  BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate,
} from 'react-router-dom'

import { post, token, user as storedUser } from './api'
import { flush, outbox } from './db'
import { ago } from './lib/data'
import * as I from './components/Icons'

import Dashboard from './pages/Dashboard'
import Enrol from './pages/Enrol'
import Facility from './pages/Facility'
import Login from './pages/Login'
import Patient from './pages/Patient'
import Patients from './pages/Patients'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Transport from './pages/Transport'
import Visits from './pages/Visits'

// The five the mockups name, in their order, and Transport. Everything else
// this platform can do lives inside one of them: the nutrition view and the
// indicators under Reports, the language workbench and the call simulator under
// Settings. A worker's primary navigation is not the place to advertise a
// developer tool.
//
// Transport is here rather than buried because Delay 2 is a third of the model
// this product is built on, and because the question it answers — is there a
// vehicle in that village — has to be answerable on a quiet afternoon. Reached
// from inside an emergency it is already too late to register anyone.
const NAV = [
  { to: '/dashboard', label: 'Dashboard', Icon: I.Home },
  { to: '/patients', label: 'Patients', Icon: I.People },
  { to: '/visits', label: 'Visits', Icon: I.Calendar },
  { to: '/transport', label: 'Transport', Icon: I.Car },
  { to: '/reports', label: 'Reports', Icon: I.Chart },
  { to: '/settings', label: 'Settings', Icon: I.Gear },
]

const SUN_KEY = 'mabia.sun'

function Shell({ children }) {
  const location = useLocation()
  const [pending, setPending] = useState(0)
  const [refused, setRefused] = useState([])
  const [online, setOnline] = useState(navigator.onLine)
  const [lastSync, setLastSync] = useState(
    Number(localStorage.getItem('mabia.lastSync')) || null)
  const [sun, setSun] = useState(localStorage.getItem(SUN_KEY) === 'on')
  const [syncing, setSyncing] = useState(false)
  const [drawer, setDrawer] = useState(false)

  useEffect(() => {
    document.documentElement.dataset.sun = sun ? 'on' : 'off'
    localStorage.setItem(SUN_KEY, sun ? 'on' : 'off')
  }, [sun])

  useEffect(() => { setDrawer(false) }, [location.pathname])

  useEffect(() => {
    const tick = async () => {
      const [sendable, rejected] = await Promise.all([
        outbox.sendable().catch(() => []),
        outbox.rejected().catch(() => []),
      ])
      // Counted separately. A record the server has refused is not "waiting to
      // send" -- no amount of waiting will send it, and folding it into that
      // number is how it stays invisible.
      setPending(sendable.length)
      setRefused(rejected)
    }
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
      setPending((await outbox.sendable().catch(() => [])).length)
      setRefused(await outbox.rejected().catch(() => []))
    } catch {
      // Stays queued. The bar keeps saying so rather than clearing the badge.
    } finally {
      setSyncing(false)
    }
  }

  useEffect(() => { if (online) sync() }, [online])

  const stale = !online || (lastSync && Date.now() - lastSync > 2 * 3600 * 1000)
  const me = storedUser.get()
  const initials = (me?.name || '')
    .split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase()
  const role = ({ cho: 'CHPS Worker', nutritionist: 'Nutrition Officer',
                  nurse: 'On-call Nurse', admin: 'Supervisor' })[me?.role]
                || 'CHPS Worker'

  return (
    <div className="shell">
      {drawer && <div className="rail-scrim" onClick={() => setDrawer(false)} />}

      {/* On a phone this same list becomes the bottom bar, because a fixed
          sidebar on a 390px screen is a drawer nobody opens. */}
      <aside className={`rail ${drawer ? 'open' : ''}`}>
        <div className="rail-brand">
          <span className="rail-mark"><I.Logo /></span>
          <span className="rail-name">
            Mabia AI
            <span>Care Network</span>
          </span>
        </div>
        <div className="rail-kicker">CHPS Worker System</div>

        <nav aria-label="Sections">
          {NAV.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to}
                     className={({ isActive }) => isActive ? 'active' : ''}>
              <Icon />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="rail-foot">
          <div className="rail-status">
            <div className="t"><I.Cloud /> System Status</div>
            <div className="r">
              <span className={`dot ${online ? '' : 'off'}`} />
              {online ? 'Online' : 'Offline'}
            </div>
            <div className="s">Last sync: {ago(lastSync)}</div>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="burger" onClick={() => setDrawer(d => !d)}
                  aria-label="Menu"><I.Burger /></button>

          <span className="spacer" />

          <div className="sysline">
            <span className={`dot ${online ? '' : 'off'}`} />
            <span>
              <span className="l" style={{ display: 'block' }}>
                {online ? 'Online' : 'Offline'}
              </span>
              <span className="s">
                {online ? 'All systems operational' : 'Working from this phone'}
              </span>
            </span>
          </div>

          <span className="topdiv" />

          <button className="bell" onClick={sync}
                  aria-label={`${refused.length + pending} items need attention`}>
            <I.Bell />
            {(refused.length + pending) > 0 && (
              <span className="count">{refused.length + pending}</span>
            )}
          </button>

          <span className="topdiv" />

          <div className="whoami">
            <span className="avatar">{initials || '—'}</span>
            <span className="whotext">
              <span className="n">{me?.name || 'Signed in'}</span>
              <span className="r">{role}</span>
            </span>
            <button className="quiet small" onClick={() => setSun(s => !s)}
                    aria-pressed={sun}
                    title="Maximum contrast, for a screen in direct sunlight">
              {sun ? 'Sun on' : 'Sun'}
            </button>
          </div>
        </header>

        {/* The server refused these and this device is the only copy. Loud,
            permanent until dealt with, and never folded into "waiting to
            send" -- waiting is exactly what will not fix them. */}
        {refused.length > 0 && (
          <div className="notice bad" role="alert"
               style={{ borderRadius: 0, borderWidth: '0 0 1px' }}>
            <strong>{refused.length} record{refused.length > 1 ? 's' : ''} could
            not be saved.</strong> They are still on this phone and nothing has
            been lost, but they need fixing before they will go.
            <ul style={{ margin: '.4rem 0 0 1.1rem', padding: 0 }}>
              {refused.slice(0, 4).map(r => (
                <li key={r.event_id}>
                  {(r.event_type || 'record').replace(/_/g, ' ')} — {r.rejected_reason}
                </li>
              ))}
            </ul>
            {refused.length > 4 && <div>…and {refused.length - 4} more.</div>}
          </div>
        )}

        {/* Always present, never a toast: how old this is, and what is waiting. */}
        <div className={`syncbar ${stale ? 'stale' : ''}`} role="status">
          <span>
            {online ? `Synced ${ago(lastSync)}`
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

        <main className="page">{children}</main>
      </div>

      <nav className="tabbar" aria-label="Main">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink key={to} to={to}
                   className={({ isActive }) => isActive ? 'active' : ''}>
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export function BackLink({ to = '/patients', label = 'Back to Patients' }) {
  const navigate = useNavigate()
  return (
    <button className="quiet small" style={{ marginBottom: 14, paddingLeft: 0 }}
            onClick={() => navigate(to)}>
      <I.Back size={17} /> {label}
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
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Guard><Dashboard /></Guard>} />
        <Route path="/patients" element={<Guard><Patients /></Guard>} />
        <Route path="/patients/:id" element={<Guard><Patient /></Guard>} />
        <Route path="/visits" element={<Guard><Visits /></Guard>} />
        <Route path="/visits/enrol" element={<Guard><Enrol /></Guard>} />
        <Route path="/visits/facility" element={<Guard><Facility /></Guard>} />
        <Route path="/transport" element={<Guard><Transport /></Guard>} />
        <Route path="/reports" element={<Guard><Reports /></Guard>} />
        <Route path="/settings" element={<Guard><Settings /></Guard>} />
        {/* The old addresses still resolve; a bookmark should not break. */}
        <Route path="/worklist" element={<Navigate to="/dashboard" replace />} />
        <Route path="/enrol" element={<Navigate to="/visits/enrol" replace />} />
        <Route path="/facility" element={<Navigate to="/visits/facility" replace />} />
        <Route path="/metrics" element={<Navigate to="/reports" replace />} />
        <Route path="/nutrition" element={<Navigate to="/reports?view=nutrition" replace />} />
        <Route path="/voice" element={<Navigate to="/settings?view=voice" replace />} />
        <Route path="/simulator" element={<Navigate to="/settings?view=calls" replace />} />
        <Route path="/setup" element={<Navigate to="/settings" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
