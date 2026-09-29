export function createTypewriter(onText, requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame) {
  let received = []
  let shown = 0
  let frame = null
  let lastTick = null
  let lastRender = null
  let credit = 0

  function tick(time) {
    frame = null
    const elapsed = lastTick === null ? 0 : Math.max(0, time - lastTick)
    lastTick = time
    const backlog = received.length - shown
    const speed = backlog > 80 ? Math.max(360, backlog * 3) : 150
    credit += elapsed * speed / 1000
    if (lastRender === null || time - lastRender >= 50) {
      const count = Math.min(backlog, Math.floor(credit))
      if (count > 0) {
        shown += count
        credit -= count
        lastRender = time
        onText(received.slice(0, shown).join(''))
      }
    }
    if (shown < received.length) frame = requestFrame(tick)
    else { lastTick = null; credit = 0 }
  }

  function cancel() {
    if (frame !== null) cancelFrame(frame)
    frame = null
    received = []
    shown = 0
    lastTick = null
    lastRender = null
    credit = 0
  }

  return {
    append(text) {
      received.push(...Array.from(text || ''))
      if (shown < received.length && frame === null) frame = requestFrame(tick)
    },
    finish() {
      const text = received.join('')
      cancel()
      onText(text)
    },
    cancel
  }
}
