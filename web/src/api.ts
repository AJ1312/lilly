export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

let csrf = ''
let onSignedOut: () => void = () => {}

export function configureApi(token: string, signedOut: () => void): void {
  csrf = token
  onSignedOut = signedOut
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Lilly-CSRF': csrf }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Cannot reach Lilly. Is it still running?', 0)
  }
  const data: unknown = await res.json().catch(() => ({}))
  const message = (data as { error?: string }).error
  if (res.status === 401 && path !== '/api/login') onSignedOut()
  if (!res.ok) throw new ApiError(message ?? `Request failed (${res.status})`, res.status)
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body: unknown = {}) => request<T>('POST', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong'
}
