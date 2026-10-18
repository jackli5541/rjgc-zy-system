export function selectionActionPosition(anchor, size, viewport, obstacle) {
  const margin = 8
  const clamp = point => ({
    left: Math.max(margin, Math.min(point.left, viewport.width - size.width - margin)),
    top: Math.max(margin, Math.min(point.top, viewport.height - size.height - margin))
  })
  const preferred = clamp(anchor)
  const overlaps = point => obstacle && point.left < obstacle.right + margin &&
    point.left + size.width > obstacle.left - margin && point.top < obstacle.bottom + margin &&
    point.top + size.height > obstacle.top - margin
  if (!overlaps(preferred)) return { ...preferred, behindChat: false }
  const candidates = [
    { left: obstacle.right + margin, top: preferred.top },
    { left: obstacle.left - size.width - margin, top: preferred.top },
    { left: preferred.left, top: obstacle.bottom + margin },
    { left: preferred.left, top: obstacle.top - size.height - margin }
  ].map(clamp).filter(point => !overlaps(point))
  candidates.sort((a, b) => Math.hypot(a.left - preferred.left, a.top - preferred.top) - Math.hypot(b.left - preferred.left, b.top - preferred.top))
  // A window filling the viewport leaves no room; keep its contents unobstructed.
  return { ...(candidates[0] || preferred), behindChat: !candidates.length }
}
