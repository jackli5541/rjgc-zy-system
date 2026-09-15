let csrfToken = ''

export function setCsrfToken(value) { csrfToken = value || '' }

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (csrfToken && !['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) headers.set('X-CSRF-Token', csrfToken)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api/v1${path}`, { credentials: 'include', ...options, headers })
  if (response.status === 401 && window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  const data = type.includes('json') ? await response.json() : await response.text()
  if (!response.ok) throw new Error(data?.message || data?.detail?.message || '请求失败，请稍后重试')
  return data
}
