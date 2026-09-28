export function normalizeCandidateMessage(candidateMessage) {
  if (typeof candidateMessage === 'string') return candidateMessage
  if (
    candidateMessage
    && typeof candidateMessage === 'object'
    && typeof candidateMessage.text === 'string'
  ) {
    return candidateMessage.text
  }
  return ''
}
