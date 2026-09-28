import assert from 'node:assert/strict'

import { normalizeCandidateMessage } from '../src/utils/chatMessage.js'

assert.equal(normalizeCandidateMessage('xxx'), 'xxx')
assert.equal(normalizeCandidateMessage({ text: 'xxx' }), 'xxx')
assert.equal(normalizeCandidateMessage({ text: 123 }), '')
assert.equal(normalizeCandidateMessage(null), '')

console.log('chat message input tests passed')
