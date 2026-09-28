import assert from 'node:assert/strict'

import {
  DEMO_SESSION_STORAGE_KEY,
  clearDemoSession,
  loadDemoSession,
  saveDemoSession,
} from '../src/utils/demoSession.js'

class MemoryStorage {
  values = new Map()

  getItem(key) { return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(key, value) }
  removeItem(key) { this.values.delete(key) }
}

const storage = new MemoryStorage()
const session = {
  workflow_id: 'workflow-1',
  session_id: 'session-1',
  task_summary: { product: 'KQ-Z112', bom_version: 'V01', quantity: 100 },
}

saveDemoSession(storage, session)
assert.deepEqual(loadDemoSession(storage), session)

storage.setItem(DEMO_SESSION_STORAGE_KEY, '{invalid-json')
assert.equal(loadDemoSession(storage), null)

saveDemoSession(storage, session)
clearDemoSession(storage)
assert.equal(storage.getItem(DEMO_SESSION_STORAGE_KEY), null)

console.log('demoSession tests passed')
