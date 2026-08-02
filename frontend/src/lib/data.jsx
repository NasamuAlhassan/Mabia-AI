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

  const reload = useCallback(async ({ quiet = false } = {}) => {
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
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000))
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
