import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { ApiError, queryAgent } from '../src/api/pmc.js'

const originalFetch = globalThis.fetch
const calls = []

try {
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return {
      ok: true,
      json: async () => ({ intent: 'fact_query', status: 'ok', answer: '已查询', structured_data: {}, provenance: null, warnings: [] }),
    }
  }

  await queryAgent('查询 MAT-001 库存')
  assert.equal(calls[0].url, 'http://localhost:8000/api/v1/agent/query')
  assert.equal(calls[0].options.method, 'POST')
  assert.deepEqual(JSON.parse(calls[0].options.body), { message: '查询 MAT-001 库存' })

  await queryAgent('为什么不能生产？', 'workflow-1')
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    message: '为什么不能生产？',
    workflow_id: 'workflow-1',
  })

  await queryAgent('还能用吗？', 'workflow-1', 'fact-session-1', 'fact_query')
  assert.deepEqual(JSON.parse(calls[2].options.body), {
    message: '还能用吗？',
    workflow_id: 'workflow-1',
    fact_session_id: 'fact-session-1',
    active_context: 'fact_query',
  })

  globalThis.fetch = async () => ({
    ok: false,
    status: 500,
    json: async () => ({ code: 'ANALYSIS_UNAVAILABLE', user_message: '分析服务暂时异常，请稍后重试。' }),
  })
  await assert.rejects(() => queryAgent('查询库存'), (error) => (
    error instanceof ApiError
    && error.code === 'ANALYSIS_UNAVAILABLE'
    && error.message === '分析服务暂时异常，请稍后重试。'
  ))

  const chatView = readFileSync(new URL('../src/views/Chat.vue', import.meta.url), 'utf8')
  assert.match(chatView, /await queryAgent\(/)
  assert.match(chatView, /factSessionId\.value = envelope\.structured_data\.fact_session_id/)
  assert.match(chatView, /factSessionId\.value = null/)
  assert.doesNotMatch(chatView, /await chatPmc\(/)
} finally {
  globalThis.fetch = originalFetch
}

console.log('agent API tests passed')
