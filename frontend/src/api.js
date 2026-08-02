// Talking to the backend, and remembering who we are.

const BASE = import.meta.env.VITE_API_BASE || ''
const TOKEN_KEY = 'mabia.token'
const USER_KEY = 'mabia.user'

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY) },
}

export const user = {
  get: () => { try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null } },
  set: (u) => localStorage.setItem(USER_KEY, JSON.stringify(u)),
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status }
}

export async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const t = token.get()
  if (auth && t) headers.Authorization = `Bearer ${t}`

  let res
  try {
    res = await fetch(BASE + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    // Offline is the normal case here, not the exception.
    throw new ApiError('offline', 0)
  }

  if (res.status === 401) { token.clear(); throw new ApiError('Session expired', 401) }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { const j = await res.json(); detail = j.detail || detail } catch {}
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return null
  return res.json()
}

export const get = (p) => api(p)
export const post = (p, body) => api(p, { method: 'POST', body })
export const put = (p, body) => api(p, { method: 'PUT', body })

export async function upload(path, blob, filename) {
  const form = new FormData()
  form.append('file', blob, filename)
  const headers = {}
  const t = token.get()
  if (t) headers.Authorization = `Bearer ${t}`

  let res
  try {
    res = await fetch(BASE + path, { method: 'POST', headers, body: form })
  } catch {
    throw new ApiError('offline', 0)
  }
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`
    try { const j = await res.json(); detail = j.detail || detail } catch {}
    throw new ApiError(detail, res.status)
  }
  return res.json()
}

export async function login(phone, pin) {
  const out = await api('/api/auth/login', {
    method: 'POST', body: { phone, pin }, auth: false,
  })
  token.set(out.token); user.set(out.user)
  return out.user
}
