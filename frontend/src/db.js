// The offline outbox.
//
// Work recorded in a compound with no signal has to survive until there is one.
// Every entry carries a client-generated, time-sortable id, and the server
// de-duplicates on it -- so flushing twice is harmless, which is what makes a
// flaky link survivable rather than merely annoying.

const DB_NAME = 'mabia'
const STORE = 'outbox'
const CACHE = 'cache'

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: 'event_id' })
      if (!db.objectStoreNames.contains(CACHE)) db.createObjectStore(CACHE)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function tx(store, mode, fn) {
  return open().then(db => new Promise((resolve, reject) => {
    const t = db.transaction(store, mode)
    const s = t.objectStore(store)
    const out = fn(s)
    t.oncomplete = () => resolve(out?.result ?? out)
    t.onerror = () => reject(t.error)
  }))
}

// UUIDv7: time-sortable, so replay order is chronological order.
export function uuid7() {
  const ms = Date.now()
  const bytes = crypto.getRandomValues(new Uint8Array(10))
  const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('')
  const t = ms.toString(16).padStart(12, '0')
  return `${t.slice(0, 8)}-${t.slice(8, 12)}-7${hex.slice(0, 3)}-` +
         `${((parseInt(hex.slice(3, 4), 16) & 0x3 | 0x8).toString(16))}${hex.slice(4, 7)}-${hex.slice(7, 19)}`
}

export const outbox = {
  async add(event) {
    const entry = { event_id: event.event_id || uuid7(), device_id: deviceId(), ...event }
    await tx(STORE, 'readwrite', s => s.put(entry))
    return entry
  },
  async all() { return tx(STORE, 'readonly', s => s.getAll()) },
  async count() { return tx(STORE, 'readonly', s => s.count()) },
  async remove(ids) {
    return tx(STORE, 'readwrite', s => { ids.forEach(id => s.delete(id)) })
  },
}

export const cache = {
  async set(key, value) { return tx(CACHE, 'readwrite', s => s.put(value, key)) },
  async get(key) { return tx(CACHE, 'readonly', s => s.get(key)) },
}

// One id per browser, not per user: two people often share one CHPS login, and
// they are still two people at two devices.
export function deviceId() {
  let id = localStorage.getItem('mabia.device')
  if (!id) { id = uuid7(); localStorage.setItem('mabia.device', id) }
  return id
}

export async function flush(post) {
  const pending = await outbox.all()
  if (!pending.length) return { sent: 0 }
  const events = pending.map(e => ({
    event_id: e.event_id, patient_id: e.patient_id, event_type: e.event_type,
    payload: e.payload || {}, occurred_at: e.occurred_at,
    recorded_at: e.recorded_at || e.occurred_at, device_id: e.device_id, seq: e.seq || 0,
  }))
  const out = await post('/api/sync/push', { events })
  await outbox.remove(pending.map(e => e.event_id))
  return { sent: events.length, ...out }
}
