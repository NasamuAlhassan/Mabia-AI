import { useEffect, useState } from 'react'
import {
  BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useLocation,
  useNavigate,
} from 'react-router-dom'

import { post, token, user as storedUser } from './api'
import { flush, outbox } from './db'
import { ago, useData } from './lib/data'
import * as I from './components/Icons'
import { AttentionMenu, UserMenu } from './components/HeaderMenus'
import { Toaster, toast } from './components/Toast'

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

const TITLES = [
  ['/patients/', 'Patient record'], ['/visits/enrol', 'Enrol a household'],
  ['/visits/facility', 'Facility'], ['/dashboard', 'Dashboard'],
  ['/patients', 'Patients'], ['/visits', 'Visits'], ['/transport', 'Transport'],
  ['/reports', 'Reports'], ['/settings', 'Settings'],
]

function Shell({ children }) {
  const location = useLocation()
  const [pending, setPending] = useState(0)
  const [refused, setRefused] = useState([])
  const [online, setOnline] = useState(navigator.onLine)
  const [lastSync, setLastSync] = useState(
    Number(localStorage.getItem('mabia.lastSync')) || null)
  const [sun, setSun] = useState(localStorage.getItem(SUN_KEY) === 'on')
  const [syncing, setSyncing] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  // An open emergency is visible from every screen. It used to live only on the
  // dashboard, so a worker reading a patient record or filling in an enrolment
  // could sit beside one for as long as it took her to go back and look.
  const emergencies = useData('/api/emergencies', { interval: 30000 })
  const waiting = (emergencies.data || []).filter(e => e.status === 'pending_validation')

  useEffect(() => {
    const entry = TITLES.find(([prefix]) => location.pathname.startsWith(prefix))
    document.title = `${waiting.length ? `(${waiting.length}) ` : ''}${entry ? entry[1] + ' · ' : ''}Mabia AI`
  }, [location.pathname, waiting.length])

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 4)
    on()
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.sun = sun ? 'on' : 'off'
    localStorage.setItem(SUN_KEY, sun ? 'on' : 'off')
  }, [sun])

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

  async function sync({ announce = false } = {}) {
    setSyncing(true)
    try {
      const out = await flush(post)
      const now = Date.now()
      setLastSync(now)
      localStorage.setItem('mabia.lastSync', String(now))
      const left = (await outbox.sendable().catch(() => [])).length
      setPending(left)
      setRefused(await outbox.rejected().catch(() => []))
      if (announce) {
        toast(out?.sent ? `Sent ${out.sent} ${out.sent === 1 ? 'record' : 'records'}.`
                         : 'Up to date. Nothing was waiting.')
      }
      emergencies.reload({ quiet: true })
    } catch {
      // Stays queued. The bar keeps saying so rather than clearing the badge.
      if (announce) toast('Could not reach the server. Your records are safe on this phone.', 'bad')
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
      <a href="#main" className="skip">Skip to content</a>
      <header className={`topbar ${scrolled ? 'scrolled' : ''}`}>
        <NavLink to="/dashboard" className="brand" aria-label="Mabia AI, dashboard">
          <span className="rail-mark"><I.Logo /></span>
          <span className="rail-name">
            Mabia AI
            <span>Care Network</span>
          </span>
        </NavLink>

        {/* The sections, as a floating pill. On a phone this same list is the
            bottom bar, because a menu button hides the one thing she needs. */}
        <nav className="pillnav" aria-label="Sections">
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to}
                     className={({ isActive }) => isActive ? 'active' : ''}>
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="toolbar">
          <div className="sysline" role="status">
            <span className={`dot ${online ? '' : 'off'}`} />
            <span>
              <span className="l">{online ? 'Online' : 'Offline'}</span>
              <span className="s">
                {online ? 'All systems operational' : 'Working from this phone'}
              </span>
            </span>
          </div>

          <span className="topdiv" />

          <AttentionMenu emergencies={waiting} pending={pending} refused={refused}
                         syncing={syncing} online={online}
                         onSync={() => sync({ announce: true })} />

          <button className="sunbtn small" onClick={() => setSun(s => !s)}
                  aria-pressed={sun}
                  title="Maximum contrast, for a screen in direct sunlight">
            Sunlight
          </button>

          <UserMenu me={me} initials={initials} role={role} sun={sun}
                    setSun={setSun} pending={pending} />
        </div>
      </header>

      <div className="main">
        {waiting.length > 0 && !location.pathname.startsWith('/dashboard') && (
          <Link className="alarmbar" role="alert"
                to={waiting[0].patient?.id ? `/patients/${waiting[0].patient.id}` : '/dashboard'}>
            <I.Warning size={18} />
            <span>
              <strong>
                {waiting.length === 1 ? (waiting[0].patient?.name || 'An emergency')
                                       : `${waiting.length} emergencies`}
              </strong>
              {' '}{waiting.length === 1 ? 'is waiting for you to respond.' : 'are waiting for you to respond.'}
            </span>
            <span className="alarmbar-go">Open <I.Chevron size={14} /></span>
          </Link>
        )}

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
            <button onClick={() => sync({ announce: true })} disabled={syncing}>
              {syncing ? <span className="spin" /> : 'Sync now'}
            </button>
          )}
        </div>

        <main className="page enter" id="main" tabIndex={-1} key={location.pathname}>{children}</main>
      </div>

      <Toaster />

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

// One shell for every signed-in screen. It used to be wrapped around each page
// separately, which threw the header away and rebuilt it -- and re-ran the sync
// and the emergency poll -- on every single navigation.
function Layout() {
  if (!token.get()) return <Navigate to="/login" replace />
  return <Shell><Outlet /></Shell>
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
        <Route element={<Layout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/patients" element={<Patients />} />
          <Route path="/patients/:id" element={<Patient />} />
          <Route path="/visits" element={<Visits />} />
          <Route path="/visits/enrol" element={<Enrol />} />
          <Route path="/visits/facility" element={<Facility />} />
          <Route path="/transport" element={<Transport />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
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
