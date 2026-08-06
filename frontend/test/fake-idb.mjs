// A minimum IndexedDB, enough to run the outbox for real rather than mock it.
//
// The outbox is the one piece of this app whose failure loses a household's
// record permanently, and it had no tests at all. Faking the store rather than
// stubbing the module means the code under test is the code that ships.

class Store {
  constructor(keyPath) { this.keyPath = keyPath; this.rows = new Map() }
  put(value, key) {
    this.rows.set(this.keyPath ? value[this.keyPath] : key, value)
    return { result: undefined }
  }
  get(key) { return { result: this.rows.get(key) } }
  getAll() { return { result: [...this.rows.values()] } }
  count() { return { result: this.rows.size } }
  delete(key) { this.rows.delete(key); return { result: undefined } }
}

export function install() {
  // The fake never fires onupgradeneeded, so every store the app expects has
  // to exist from the start. `vault` holds the record key.
  const stores = {
    outbox: new Store('event_id'),
    cache: new Store(null),
    vault: new Store(null),
  }

  globalThis.indexedDB = {
    open() {
      const req = {}
      queueMicrotask(() => {
        req.result = {
          objectStoreNames: { contains: (n) => n in stores },
          createObjectStore: (n, o) => (stores[n] = new Store(o?.keyPath ?? null)),
          transaction(name) {
            const t = {}
            queueMicrotask(() => t.oncomplete && t.oncomplete())
            t.objectStore = () => stores[name]
            return t
          },
        }
        req.onsuccess && req.onsuccess()
      })
      return req
    },
  }

  const memory = new Map()
  globalThis.localStorage = {
    getItem: (k) => (memory.has(k) ? memory.get(k) : null),
    setItem: (k, v) => memory.set(k, String(v)),
    removeItem: (k) => memory.delete(k),
  }
  return stores
}
