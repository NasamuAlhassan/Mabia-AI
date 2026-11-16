import { useEffect, useState } from 'react'
import * as I from './Icons'

// Confirmation that something happened, which then gets out of the way.
//
// Mounted once, in the shell. `toast('Synced')` from anywhere. One polite live
// region, so a screen reader hears each message once and a sighted person sees
// it for long enough to read it and no longer.

const listeners = new Set()
let nextId = 1

export function toast(text, tone = 'ok') {
  const item = { id: nextId++, text, tone }
  listeners.forEach(fn => fn(item))
}

export function Toaster() {
  const [items, setItems] = useState([])

  useEffect(() => {
    const add = (item) => {
      setItems(list => [...list.slice(-2), item])
      setTimeout(() => setItems(list => list.filter(x => x.id !== item.id)),
                 item.tone === 'bad' ? 6000 : 3500)
    }
    listeners.add(add)
    return () => { listeners.delete(add) }
  }, [])

  return (
    <div className="toaster" role="status" aria-live="polite">
      {items.map(t => (
        <div key={t.id} className={`toast ${t.tone}`}>
          {t.tone === 'ok' ? <I.Check size={16} /> : <I.Info size={16} />}
          {t.text}
        </div>
      ))}
    </div>
  )
}
