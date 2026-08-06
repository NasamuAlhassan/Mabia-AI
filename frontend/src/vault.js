// Encryption at rest, for the records this phone is holding.
//
// A CHPS handset goes into a compound, a bag and a market. What sits on it
// between a visit and the next bar of signal is a woman's name, her phone
// number, what she reported and how far she is from care. Until now that sat in
// IndexedDB as readable JSON: anyone who took the phone and opened the browser
// profile could read every household on it without ever signing in.
//
// So the clinical content of every queued event, and every cached response, is
// encrypted with AES-GCM before it touches the disk.
//
// What this protects against, stated plainly, because a security claim nobody
// has bounded is worse than none:
//
//   It protects against someone who takes the handset and reads the browser's
//   storage directly -- devtools, a copied profile, a forensic dump. That is
//   the realistic threat for a phone that lives in a bag.
//
//   It does not protect against someone who picks up the unlocked phone and
//   opens the app. The session token is in localStorage and the app will show
//   them the caseload, exactly as it would show the worker. The answer to that
//   is the phone's own lock screen, which is not ours to provide.
//
//   It does not protect against script running on this origin. Nothing in a
//   browser can.
//
// The key is generated here and stored as a non-extractable CryptoKey, so the
// raw bytes cannot be read back out by any code -- including this file. The
// browser holds it; we hold a handle.
//
// It is deliberately not derived from the worker's PIN. The session token
// already survives a reload, so a PIN-derived key would be lost on refresh
// while the app stayed signed in, leaving it unable to read its own outbox --
// and a four-digit PIN is ten thousand guesses, which is minutes of work
// against a copied database whatever the derivation cost.
//
// And it is deliberately never destroyed on sign-out. Doing so would make any
// unsent work in the outbox permanently unreadable, and the outbox is by
// definition the only copy of it. Losing a household while reporting success is
// the worst thing this app can do; losing one while reporting a sign-out is the
// same thing wearing a different hat.

const VAULT = 'vault'
const KEY_ID = 'record-key'

let cached = null

// Set by db.js so this file does not open its own connection -- two connections
// to the same database race on the upgrade and one of them blocks forever.
let store = null
export function useStore(fn) { store = fn }

async function key() {
  if (cached) return cached
  if (!store) throw new Error('vault: no store bound')

  const existing = await store('readonly', s => s.get(KEY_ID))
  if (existing) { cached = existing; return cached }

  const fresh = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 },
    false,                       // non-extractable: the bytes never come back out
    ['encrypt', 'decrypt'],
  )
  await store('readwrite', s => s.put(fresh, KEY_ID))
  cached = fresh
  return cached
}

// A marker, so a record written before this existed is recognised as plaintext
// and read straight through rather than handed to the decryptor as ciphertext.
export function isSealed(v) {
  return !!v && typeof v === 'object' && v.__enc === 1
}

export async function seal(value) {
  if (value === undefined || value === null) return value
  const k = await key()
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const bytes = new TextEncoder().encode(JSON.stringify(value))
  const out = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, k, bytes)
  return { __enc: 1, iv: [...iv], data: [...new Uint8Array(out)] }
}

export async function open(value) {
  if (!isSealed(value)) return value
  const k = await key()
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: Uint8Array.from(value.iv) },
    k,
    Uint8Array.from(value.data),
  )
  return JSON.parse(new TextDecoder().decode(plain))
}

// Whether what is actually on this disk is encrypted -- not whether encryption
// is switched on. Settings reports this one, because a worker deciding whether
// a lost handset matters needs the state of the data, not of the intention.
export async function state() {
  if (!store) return { ok: false, reason: 'not started' }
  try {
    const k = await store('readonly', s => s.get(KEY_ID))
    return { ok: !!k, reason: k ? null : 'no key yet — nothing has been saved' }
  } catch (e) {
    return { ok: false, reason: e.message }
  }
}
