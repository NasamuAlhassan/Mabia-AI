// The offline outbox.
//
// Work recorded in a compound with no signal has to survive until there is one.
// Every entry carries a client-generated, time-sortable id, and the server
// de-duplicates on it -- so flushing twice is harmless, which is what makes a
// flaky link survivable rather than merely annoying.

import * as vault from './vault.js'

const DB_NAME = 'mabia'
const STORE = 'outbox'
const CACHE = 'cache'
const VAULT = 'vault'

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 2)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: 'event_id' })
      if (!db.objectStoreNames.contains(CACHE)) db.createObjectStore(CACHE)
      // Holds one non-extractable CryptoKey. Records written before it existed
      // stay readable: seal() marks what it wrote and open() passes anything
      // unmarked straight through.
      if (!db.objectStoreNames.contains(VAULT)) db.createObjectStore(VAULT)
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
    // `out?.result ?? out` looked equivalent and was not. A lookup that misses
    // resolves with result === undefined, so ?? fell through and handed the
    // caller the IDBRequest itself -- an object, and therefore truthy. Callers
    // asking "is there a cached copy of this?" were told yes and then read
    // .data off a request, getting undefined. That is what put "Could not load
    // this" on screens whose data was fine: the first fetch of a session loses
    // a race, the cache is consulted, the miss reads as a hit, and the page
    // renders a failure it then recovers from on retry.
    t.oncomplete = () => resolve(
      out && typeof out === 'object' && 'result' in out ? out.result : out,
    )
    t.onerror = () => reject(t.error)
  }))
}

// The vault reads and writes through this connection rather than opening a
// second one -- two connections race on the upgrade and one blocks forever.
vault.useStore((mode, fn) => tx(VAULT, mode, fn))

// The clinical content is the payload. The envelope -- id, patient, type, when,
// device, seq -- stays readable so the outbox can sort, de-duplicate and report
// what it is holding without decrypting anything.
async function sealed(entry) {
  if (!entry || entry.payload === undefined) return entry
  return { ...entry, payload: await vault.seal(entry.payload) }
}

async function opened(entry) {
  if (!entry || entry.payload === undefined) return entry
  return { ...entry, payload: await vault.open(entry.payload) }
}

// UUIDv7: time-sortable, so replay order is chronological order.
//
// The millisecond alone is not enough. Recording one visit writes several
// events -- the measurement, the danger signs, the note -- and on any modern
// handset those land in the same millisecond, where a purely random tail orders
// them arbitrarily. The server breaks ties on (occurred_at, device_id, seq),
// and every event carried seq 0, so there was nothing to break the tie with:
// two observations of the same type written milliseconds apart could fold in
// either order, and the fold decides what her record says.
//
// So the twelve bits after the version are a counter, per millisecond, as the
// UUIDv7 specification allows. 4096 events in one millisecond on a phone is not
// a situation worth designing for beyond falling back to random.
let lastMs = 0
let counter = 0

export function uuid7() {
  const ms = Date.now()
  if (ms === lastMs) {
    counter += 1
  } else {
    lastMs = ms
    counter = 0
  }

  const bytes = crypto.getRandomValues(new Uint8Array(10))
  const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('')
  const t = ms.toString(16).padStart(12, '0')
  const seq = counter < 0x1000
    ? counter.toString(16).padStart(3, '0')
    : hex.slice(0, 3)

  return `${t.slice(0, 8)}-${t.slice(8, 12)}-7${seq}-` +
         `${((parseInt(hex.slice(3, 4), 16) & 0x3 | 0x8).toString(16))}${hex.slice(4, 7)}-${hex.slice(7, 19)}`
}

// The same counter, handed to the server so its own tiebreak works. It orders
// events written in one millisecond; it is not a global sequence number.
export function nextSeq() { return counter }

export const outbox = {
  async add(event) {
    const id = event.event_id || uuid7()
    const entry = {
      event_id: id, device_id: deviceId(), seq: nextSeq(), ...event,
    }
    const stored = await sealed(entry)
    await tx(STORE, 'readwrite', s => s.put(stored))
    return entry
  },
  async all() {
    const rows = await tx(STORE, 'readonly', s => s.getAll())
    return Promise.all(rows.map(opened))
  },
  async count() { return tx(STORE, 'readonly', s => s.count()) },
  async remove(ids) {
    return tx(STORE, 'readwrite', s => { ids.forEach(id => s.delete(id)) })
  },

  // Everything still waiting to go, excluding entries the server has already
  // refused. Retrying a rejection forever would never succeed and would keep
  // the badge spinning on work that needs a person, not another attempt.
  async sendable() {
    const all = await outbox.all()
    return all.filter(e => !e.rejected_reason)
  },

  // Refused by the server, kept on the device, waiting for someone to look.
  async rejected() {
    const all = await outbox.all()
    return all.filter(e => e.rejected_reason)
  },

  async markRejected(failures) {
    const byId = new Map(failures.map(f => [f.event_id, f.reason]))
    const all = await outbox.all()
    // Re-sealed on the way back in. These came out of all() decrypted, and
    // putting them straight back would quietly rewrite the payload in clear.
    const touched = await Promise.all(
      all.filter(e => byId.has(e.event_id)).map(e => sealed({
        ...e,
        rejected_reason: byId.get(e.event_id),
        rejected_at: new Date().toISOString(),
      })),
    )
    return tx(STORE, 'readwrite', s => { touched.forEach(e => s.put(e)) })
  },

  async discard(ids) { return outbox.remove(ids) },
}

export const cache = {
  async set(key, value) {
    const stored = await vault.seal(value)
    return tx(CACHE, 'readwrite', s => s.put(stored, key))
  },
  async get(key) {
    return vault.open(await tx(CACHE, 'readonly', s => s.get(key)))
  },
}

// One id per browser, not per user: two people often share one CHPS login, and
// they are still two people at two devices.
export function deviceId() {
  let id = localStorage.getItem('mabia.device')
  if (!id) { id = uuid7(); localStorage.setItem('mabia.device', id) }
  return id
}

export async function flush(post) {
  const pending = await outbox.sendable()
  if (!pending.length) return { sent: 0 }
  const events = pending.map(e => ({
    event_id: e.event_id, patient_id: e.patient_id, event_type: e.event_type,
    payload: e.payload || {}, occurred_at: e.occurred_at,
    recorded_at: e.recorded_at || e.occurred_at, device_id: e.device_id, seq: e.seq || 0,
  }))
  const out = await post('/api/sync/push', { events })

  // The server tells us exactly what it refused and why. This used to delete
  // the whole batch regardless -- so an enrolment missing a phone number, or a
  // visit whose danger signs arrived malformed, was thrown away on the device
  // that was the only remaining copy of it. The badge then read zero pending
  // and the worker was told her work had synced. Losing a household while
  // reporting success is the worst thing this app can do, and it was doing it
  // for exactly the records the server had taken the trouble to name.
  const failures = out?.rejected || []
  if (failures.length) await outbox.markRejected(failures)

  const refused = new Set(failures.map(f => f.event_id))
  const saved = pending.map(e => e.event_id).filter(id => !refused.has(id))
  await outbox.remove(saved)

  return { sent: saved.length, refused: failures.length, ...out }
}
