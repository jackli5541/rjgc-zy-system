function normalizeMessageId(value) {
  const text = String(value || '')
  return /^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(text)
    ? text.replace(/-/g, '').toLowerCase()
    : text
}

export function findCompletedTurn(messages, messageId) {
  if (!messageId) return null
  const index = messages.findIndex(item => item.role === 'user' && normalizeMessageId(item.id) === normalizeMessageId(messageId))
  return index >= 0 && messages[index + 1]?.role === 'assistant'
    ? { user: messages[index], assistant: messages[index + 1] }
    : null
}

export function hasCompletedTurn(messages, messageId) {
  return findCompletedTurn(messages, messageId) !== null
}

export function reconcileTurn(messages, messageId, question, quote) {
  const completed = hasCompletedTurn(messages, messageId)
  return {
    completed,
    input: completed ? '' : question,
    quote: completed ? '' : quote
  }
}
