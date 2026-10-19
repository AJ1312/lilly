export class ApiError extends Error {
  status: number
  body?: unknown

  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  if (typeof err === 'string') return err
  return 'An unexpected error occurred.'
}

let cachedCsrf: string = ''
try {
  cachedCsrf = sessionStorage.getItem('lilly_csrf') || ''
} catch {}

export function setCsrfToken(token: string) {
  if (!token) return
  cachedCsrf = token
  try {
    sessionStorage.setItem('lilly_csrf', token)
  } catch {}
}

export function getCsrfToken(): string {
  if (cachedCsrf) return cachedCsrf
  const match = document.cookie.match(/(?:^|;\s*)(?:csrftoken|csrf|lilly_csrf)=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

let csrfPromise: Promise<string> | null = null
async function ensureCsrfToken(): Promise<string> {
  const current = getCsrfToken()
  if (current) return current
  if (csrfPromise) return csrfPromise

  csrfPromise = fetch('/api/session', { credentials: 'same-origin' })
    .then((r) => (r.ok ? r.json() : null))
    .then((data: any) => {
      if (data && data.csrf) {
        setCsrfToken(data.csrf)
        return data.csrf
      }
      return ''
    })
    .catch(() => '')
    .finally(() => {
      csrfPromise = null
    })

  return csrfPromise
}

async function request<T>(path: string, options: RequestInit = {}, retryCsrf = true): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  const method = (options.method || 'GET').toUpperCase()
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    let csrf = getCsrfToken()
    if (!csrf) {
      csrf = await ensureCsrfToken()
    }
    if (csrf) {
      headers.set('x-lilly-csrf', csrf)
      headers.set('X-CSRFToken', csrf)
    }
    if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
  }

  const response = await fetch(path, { credentials: 'same-origin', ...options, headers })

  if (response.status === 204) {
    return {} as T
  }

  let data: unknown
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    try {
      data = await response.json()
    } catch {
      data = null
    }
  } else {
    data = await response.text()
  }

  if (data && typeof data === 'object' && 'csrf' in data && typeof (data as any).csrf === 'string') {
    setCsrfToken((data as any).csrf)
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    if (data && typeof data === 'object') {
      const obj = data as Record<string, unknown>
      if (typeof obj.error === 'string') {
        message = obj.error
      } else if (typeof obj.message === 'string') {
        message = obj.message
      } else if (Array.isArray(obj.problems) && obj.problems.length > 0) {
        message = obj.problems.join(', ')
      }
    } else if (typeof data === 'string' && data.trim()) {
      message = data.slice(0, 300)
    }

    if (
      response.status === 403 &&
      (message.toLowerCase().includes('csrf') || message.toLowerCase().includes('token')) &&
      retryCsrf
    ) {
      cachedCsrf = ''
      try {
        sessionStorage.removeItem('lilly_csrf')
      } catch {}
      const refreshed = await ensureCsrfToken()
      if (refreshed) {
        const retryHeaders = new Headers(options.headers || {})
        retryHeaders.set('x-lilly-csrf', refreshed)
        retryHeaders.set('X-CSRFToken', refreshed)
        return request<T>(path, { ...options, headers: retryHeaders }, false)
      }
    }

    throw new ApiError(response.status, message, data)
  }

  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
