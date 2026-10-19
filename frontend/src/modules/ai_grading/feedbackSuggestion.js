export function hasFeedbackContent(feedback) {
  return Boolean(feedback.grade || (feedback.comment || '').replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim())
}

export function normalizeFeedbackText(value, parseHtml = html => new DOMParser().parseFromString(html, 'text/html').body.textContent || '') {
  const html = String(value || '')
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '')
    .replace(/<br\b[^>]*>|<\/(?:p|div|li|h[1-6]|blockquote|pre|tr)>/gi, '\n')
  return parseHtml(html).replace(/\s+/gu, ' ').trim()
}

export function feedbackMatchesSuggestion(feedback, draft, parseHtml) {
  if (!draft || feedback.grade !== draft.suggested_grade) return false
  const expected = { ...feedback }
  applyFeedbackSuggestion(expected, draft)
  return normalizeFeedbackText(feedback.comment, parseHtml) === normalizeFeedbackText(expected.comment, parseHtml)
}

export function applyFeedbackSuggestion(feedback, draft) {
  feedback.grade = draft.suggested_grade
  // Suggestions are plain text; escape them before inserting into the rich editor.
  feedback.comment = (draft.suggested_comment || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
}
