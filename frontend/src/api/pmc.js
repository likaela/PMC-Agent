const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = typeof body.detail === 'string' ? body.detail : '请求 PMC API 失败'
    throw new ApiError(message, response.status)
  }
  return body
}

export function analyzePmc(payload) {
  return request('/api/v1/pmc/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function chatPmc(message) {
  return request('/api/v1/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export function resumePurchaseParameters(workflowId, updates) {
  return request(`/api/v1/pmc/${encodeURIComponent(workflowId)}/purchase-parameters`, {
    method: 'POST',
    body: JSON.stringify({ updates }),
  })
}
