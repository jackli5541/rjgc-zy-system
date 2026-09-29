export function hasCompletedTurn(messages, messageId) {
  const index = messages.findIndex(item => item.id === messageId && item.role === 'user')
  return index >= 0 && messages[index + 1]?.role === 'assistant'
}

export function reconcileTurn(messages, messageId, question, quote) {
  const completed = hasCompletedTurn(messages, messageId)
  return {
    completed,
    input: completed ? '' : question,
    quote: completed ? '' : quote
  }
}
