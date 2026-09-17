let csrfToken = ''
export const apiClientId = sessionStorage.getItem('coursework-client-id') || crypto.randomUUID()
sessionStorage.setItem('coursework-client-id', apiClientId)

export function setCsrfToken(value) { csrfToken = value || '' }

export async function downloadArchive(path) {
  const response = await fetch(`/api/v1${path}`, { credentials: 'include' })
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new CustomEvent('auth-expired'))
    const data = await response.json().catch(() => null)
    throw new Error(data?.message || `导出失败（${response.status}）`)
  }
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = encoded ? decodeURIComponent(encoded) : '学生档案.zip'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {})
  headers.set('X-Client-ID', apiClientId)
  if (csrfToken && !['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) headers.set('X-CSRF-Token', csrfToken)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api/v1${path}`, { credentials: 'include', ...options, headers })
  if (response.status === 401 && window.location.pathname !== '/login') window.dispatchEvent(new CustomEvent('auth-expired'))
  if (response.status === 204) return null
  const type = response.headers.get('content-type') || ''
  const data = type.includes('json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : data?.detail?.message
    const fields = data?.details?.fields
    const fieldLabels = {
      class_ids: '教学班',
      title: '标题',
      description: '说明',
      submitter_type: '提交类型',
      starts_at: '开始时间',
      due_at: '截止时间',
      auto_review_due_at: '互评截止时间'
    }
    const validationDetail = Array.isArray(fields) && fields.length
      ? fields.map(item => {
        const field = String(item.field || '').split('.').pop()
        const label = fieldLabels[field] || field || '提交内容'
        const message = String(item.message || '')
        if (message.includes('at least 2 characters')) return `${label}至少填写 2 个字符`
        if (message.includes('at least 1 character')) return `${label}不能为空`
        if (message.includes('valid datetime')) return `${label}格式不正确`
        if (message.includes('Field required')) return `请填写${label}`
        return `${label}格式不正确`
      }).join('；')
      : ''
    throw new Error(validationDetail || data?.message || detail || `请求失败（${response.status}）`)
  }
  return data
}
