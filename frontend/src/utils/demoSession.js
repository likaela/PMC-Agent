export const DEMO_SESSION_STORAGE_KEY = 'pmc-agent-demo-session'

function isTaskSummary(value) {
  return value
    && typeof value === 'object'
    && typeof value.product === 'string'
    && typeof value.bom_version === 'string'
    && Number.isInteger(value.quantity)
}

export function saveDemoSession(storage, session) {
  if (!storage || !session?.workflow_id || !session?.session_id || !isTaskSummary(session.task_summary)) return
  storage.setItem(DEMO_SESSION_STORAGE_KEY, JSON.stringify({
    workflow_id: session.workflow_id,
    session_id: session.session_id,
    task_summary: session.task_summary,
  }))
}

export function loadDemoSession(storage) {
  if (!storage) return null
  try {
    const value = JSON.parse(storage.getItem(DEMO_SESSION_STORAGE_KEY) || 'null')
    if (!value?.workflow_id || !value?.session_id || !isTaskSummary(value.task_summary)) return null
    return value
  } catch {
    return null
  }
}

export function clearDemoSession(storage) {
  storage?.removeItem(DEMO_SESSION_STORAGE_KEY)
}
