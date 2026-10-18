import { createTypewriter } from '../../shared/typewriter.js'

export function createGradingReveal(onChange, requestFrame, cancelFrame) {
  let sections = []
  let total = 0
  function render(text) {
    let remaining = Array.from(text).length
    const visible = sections.map(section => {
      const part = section.slice(0, remaining).join('')
      remaining = Math.max(0, remaining - section.length)
      return part
    })
    onChange({ reason: visible[0] || '', points: visible.slice(1, -1).filter(Boolean), comment: visible.at(-1) || '', typing: Array.from(text).length < total })
  }
  const writer = createTypewriter(render, requestFrame, cancelFrame)
  return {
    show(draft, animate = false) {
      writer.cancel()
      sections = [draft?.analysis?.grade_reason || draft?.analysis?.summary || '', ...(draft?.analysis?.review_points || []).slice(0, 3), draft?.suggested_comment || ''].map(text => Array.from(String(text)))
      const text = sections.map(section => section.join('')).join('')
      total = Array.from(text).length
      render(animate ? '' : text)
      if (animate && total) writer.append(text)
    },
    finish() { writer.finish() },
    cancel() { writer.cancel() }
  }
}
