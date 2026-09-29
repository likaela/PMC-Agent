const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status, code = 'REQUEST_FAILED') {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = typeof body.user_message === 'string' ? body.user_message : '请求 PMC API 失败，请稍后重试。'
    const code = typeof body.code === 'string' ? body.code : 'REQUEST_FAILED'
    throw new ApiError(message, response.status, code)
  }
  return body
}

export function analyzePmc(payload) {
  return request('/api/v1/pmc/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function queryAgent(message, workflowId = null, factSessionId = null, activeContext = null) {
  return request('/api/v1/agent/query', {
    method: 'POST',
    body: JSON.stringify({
      message,
      ...(workflowId ? { workflow_id: workflowId } : {}),
      ...(factSessionId ? { fact_session_id: factSessionId } : {}),
      ...(activeContext ? { active_context: activeContext } : {}),
    }),
  })
}

export function getChatHistory(workflowId) {
  return request(`/api/v1/chat/${encodeURIComponent(workflowId)}/history`)
}

export function getPmcWorkflow(workflowId) {
  return request(`/api/v1/pmc/${encodeURIComponent(workflowId)}`)
}

export function getDemoCases() {
  return request('/api/v1/demo/cases')
}

export function getDemoStatistics() {
  return request('/api/v1/demo/statistics')
}

export function submitDemoFeedback(workflowId, feedback) {
  return request('/api/v1/demo/feedback', {
    method: 'POST',
    body: JSON.stringify({ workflow_id: workflowId, feedback }),
  })
}

export function resumePurchaseParameters(workflowId, updates) {
  return request(`/api/v1/pmc/${encodeURIComponent(workflowId)}/purchase-parameters`, {
    method: 'POST',
    body: JSON.stringify({ updates }),
  })
}
