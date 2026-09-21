import { onBeforeUnmount, onMounted, ref } from 'vue'

function resolveValue(value) {
  return typeof value === 'function' ? value() : value
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum))
}

function storedWidth(key, fallback) {
  const value = Number.parseFloat(localStorage.getItem(key))
  return Number.isFinite(value) ? value : resolveValue(fallback)
}

export function useResizableDrawer({ initialWidth, minWidth, storageKey }) {
  const width = ref(storedWidth(storageKey, initialWidth))
  const resizing = ref(false)
  let startX = 0
  let startWidth = 0
  let liveWidth = width.value
  let animationFrame = 0
  let pendingWidth = null
  let drawerRoot = null
  let drawerPanel = null

  const constrainedWidth = value => clamp(value, Math.min(minWidth, window.innerWidth), window.innerWidth)

  function applyLiveWidth(value) {
    liveWidth = constrainedWidth(value)
    drawerRoot?.style.setProperty('--drawer-width', `${liveWidth}px`)
    drawerPanel?.style.setProperty('width', `${liveWidth}px`)
  }

  function applyPendingWidth() {
    animationFrame = 0
    if (pendingWidth === null) return
    applyLiveWidth(pendingWidth)
    pendingWidth = null
  }

  function move(event) {
    if (!resizing.value) return
    pendingWidth = startWidth + startX - event.clientX
    if (!animationFrame) animationFrame = requestAnimationFrame(applyPendingWidth)
  }

  function stop(event) {
    if (!resizing.value) return
    if (event?.type === 'pointerup') pendingWidth = startWidth + startX - event.clientX
    if (animationFrame) cancelAnimationFrame(animationFrame)
    applyPendingWidth()
    resizing.value = false
    width.value = liveWidth
    localStorage.setItem(storageKey, String(Math.round(width.value)))
    document.documentElement.classList.remove('horizontal-resize-active')
    drawerRoot?.classList.remove('resizing')
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerup', stop)
    document.removeEventListener('pointercancel', stop)
  }

  function start(event, currentWidth = width.value) {
    if (window.innerWidth <= 760 || event.button !== 0) return
    event.preventDefault()
    startX = event.clientX
    startWidth = constrainedWidth(currentWidth)
    drawerRoot = event.currentTarget?.closest?.('.assignment-detail-drawer, .ant-drawer') || null
    drawerPanel = drawerRoot?.classList.contains('assignment-detail-drawer') ? drawerRoot : drawerRoot?.querySelector('.ant-drawer-content-wrapper')
    applyLiveWidth(startWidth)
    resizing.value = true
    drawerRoot?.classList.add('resizing')
    document.documentElement.classList.add('horizontal-resize-active')
    document.addEventListener('pointermove', move)
    document.addEventListener('pointerup', stop)
    document.addEventListener('pointercancel', stop)
  }

  function handleWindowResize() {
    width.value = constrainedWidth(width.value)
  }

  onMounted(() => {
    width.value = constrainedWidth(width.value)
    window.addEventListener('resize', handleWindowResize)
  })
  onBeforeUnmount(() => {
    stop()
    window.removeEventListener('resize', handleWindowResize)
  })

  return { width, resizing, startResize: start }
}

export function useResizableRightPane({ initialWidth, minWidth, maxWidth = Number.POSITIVE_INFINITY, leftMinWidth, storageKey }) {
  const width = ref(storedWidth(storageKey, initialWidth))
  const resizing = ref(false)
  let boundsWidth = 0
  let startX = 0
  let startWidth = 0
  let liveWidth = width.value
  let animationFrame = 0
  let pendingWidth = null
  let resizeContainer = null

  const constrainedWidth = value => clamp(value, minWidth, Math.min(maxWidth, boundsWidth - leftMinWidth))

  function applyLiveWidth(value) {
    liveWidth = constrainedWidth(value)
    resizeContainer?.style.setProperty('--right-pane-width', `${liveWidth}px`)
  }

  function applyPendingWidth() {
    animationFrame = 0
    if (pendingWidth === null) return
    applyLiveWidth(pendingWidth)
    pendingWidth = null
  }

  function move(event) {
    if (!resizing.value) return
    pendingWidth = startWidth + startX - event.clientX
    if (!animationFrame) animationFrame = requestAnimationFrame(applyPendingWidth)
  }

  function stop(event) {
    if (!resizing.value) return
    if (event?.type === 'pointerup') pendingWidth = startWidth + startX - event.clientX
    if (animationFrame) cancelAnimationFrame(animationFrame)
    applyPendingWidth()
    resizing.value = false
    width.value = liveWidth
    localStorage.setItem(storageKey, String(Math.round(width.value)))
    document.documentElement.classList.remove('horizontal-resize-active')
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerup', stop)
    document.removeEventListener('pointercancel', stop)
  }

  function start(event, container) {
    if (window.innerWidth <= 900 || event.button !== 0 || !container) return
    event.preventDefault()
    resizeContainer = container
    boundsWidth = resizeContainer.getBoundingClientRect().width
    startX = event.clientX
    startWidth = constrainedWidth(width.value)
    applyLiveWidth(startWidth)
    resizing.value = true
    document.documentElement.classList.add('horizontal-resize-active')
    document.addEventListener('pointermove', move)
    document.addEventListener('pointerup', stop)
    document.addEventListener('pointercancel', stop)
  }

  function resizeBy(delta, container) {
    if (!container) return
    resizeContainer = container
    boundsWidth = resizeContainer.getBoundingClientRect().width
    applyLiveWidth(width.value + delta)
    width.value = liveWidth
    localStorage.setItem(storageKey, String(Math.round(width.value)))
  }

  onBeforeUnmount(stop)

  return { width, resizing, resizeBy, startResize: start }
}
