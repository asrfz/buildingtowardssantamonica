/** Backend base URL — must match FastAPI CORS (e.g. http://localhost:8000). */
export function apiBase(): string {
  const b = import.meta.env.VITE_API_BASE
  if (b && typeof b === 'string') return b.replace(/\/$/, '')
  return 'http://localhost:8000'
}

export async function apiJson<T>(
  path: string,
  init?: RequestInit
): Promise<{ ok: boolean; status: number; data: T | null; text: string }> {
  const url = `${apiBase()}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  const text = await res.text()
  let data: T | null = null
  try {
    data = text ? (JSON.parse(text) as T) : null
  } catch {
    /* non-JSON */
  }
  return { ok: res.ok, status: res.status, data, text }
}
