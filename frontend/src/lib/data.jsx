import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, get } from '../api'
import { cache } from '../db'

// Cache-first reads, with the age on screen.
//
// The old build showed a blank screen when offline, defending it as "a cached
// worklist that looks current is worse than none". Freshness honesty is right;
// blanking is not. A worker who is offline more often than online needs her
// caseload — she needs to know how old it is, which is a label, not a deletion.
//
// So: render what we have immediately, refresh behind it, and put the age in
// the chrome permanently rather than in a toast that disappears.

export function useData(path, { interval = 0, enabled = true } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [fetchedAt, setFetchedAt] = useState(null)
  const [fromCache, setFromCache] = useState(false)
  const alive = useRef(true)
  const seq = useRef(0)

  const reload = useCallback(async ({ quiet = false, attempt = 0 } = {}) => {
    if (!enabled) return
    const mine = ++seq.current
    if (!quiet) setLoading(true)
    try {
      const fresh = await get(path)
      if (!alive.current || mine !== seq.current) return   // a newer request won
      setData(fresh); setError(null); setFromCache(false)
      setFetchedAt(Date.now())
      cache.set(path, { data: fresh, at: Date.now() }).catch(() => {})
    } catch (e) {
      if (!alive.current || mine !== seq.current) return

      // One retry before declaring failure. On a 2G link the first request of a
      // session routinely loses a race -- with a token that has just been
      // written, with a dyno waking up, with a radio that has not attached yet
      // -- and telling a health worker "could not load this" when a second
      // attempt would have worked is how an app earns a reputation for being
      // broken. Auth failures are not retried: those will not fix themselves.
      const worthRetrying = !(e instanceof ApiError && e.status === 401)
      // Two, with a widening gap. One was not enough: signing in and opening a
      // record immediately still lost the race often enough to show "could not
      // load this" on a screen whose data was fine.
      if (attempt < 2 && worthRetrying) {
        await new Promise(r => setTimeout(r, 400 * (attempt + 1)))
        if (!alive.current) return
        return reload({ quiet, attempt: attempt + 1 })
      }

      const cached = await cache.get(path).catch(() => null)
      if (cached) {
        setData(cached.data); setFetchedAt(cached.at); setFromCache(true)
        setError(e instanceof ApiError && e.status === 0 ? null : e)
      } else {
        setError(e)
      }
    } finally {
      if (alive.current && mine === seq.current) setLoading(false)
    }
  }, [path, enabled])

  useEffect(() => {
    alive.current = true
    // Paint from cache before the network is even attempted.
    cache.get(path).then(cached => {
      if (cached && alive.current && !data) {
        setData(cached.data); setFetchedAt(cached.at); setFromCache(true)
        setLoading(false)
      }
    }).catch(() => {})
    reload({ quiet: true })
    return () => { alive.current = false }
  }, [path])

  useEffect(() => {
    if (!interval) return
    // Poll only while the tab is actually being looked at. The old build polled
    // four endpoints forever, which on a bundle she pays for herself is real
    // money for data nobody is reading.
    const tick = () => { if (!document.hidden) reload({ quiet: true }) }
    const timer = setInterval(tick, interval)
    document.addEventListener('visibilitychange', tick)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [interval, reload])

  return { data, error, loading, fetchedAt, fromCache, reload }
}

export function ago(timestamp) {
  if (!timestamp) return 'never'
  // Accepts a millisecond number or an ISO string. It only ever received the
  // first, so the day a server timestamp reached it the screen read
  // "NaN days ago" beside an open emergency.
  const at = typeof timestamp === 'number' ? timestamp : Date.parse(timestamp)
  if (Number.isNaN(at)) return 'unknown'
  const seconds = Math.max(0, Math.round((Date.now() - at) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  return `${Math.round(hours / 24)} days ago`
}

export function Skeleton({ rows = 4 }) {
  return (
    <div role="status" aria-label="Loading">
      <span className="sr-only">Loading</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div className="skeleton row-lg" key={i} />
      ))}
    </div>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <div className="big">{title}</div>
      {children && <div className="muted">{children}</div>}
    </div>
  )
}

export function Failed({ error, onRetry }) {
  const offline = error instanceof ApiError && error.status === 0
  return (
    <div className="notice bad" role="alert">
      <strong>{offline ? 'No connection' : 'Could not load this'}</strong>
      <div className="tiny" style={{ marginTop: 4 }}>
        {offline
          ? 'Nothing has been saved on this device yet, so there is nothing to show.'
          : error?.message}
      </div>
      {onRetry && (
        <button className="small" style={{ marginTop: 8 }} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}
