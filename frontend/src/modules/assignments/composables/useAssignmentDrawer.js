import { ref } from 'vue'

export function useAssignmentDrawer(ctx) {
  const DRAWER_EXPANDED_STORAGE_KEY = 'assignment-drawers-expanded'

  const DRAWER_COLLAPSED_RATIO = .82

  const assignmentDrawerExpanded = ref(localStorage.getItem(DRAWER_EXPANDED_STORAGE_KEY) === 'true')

  const peerReviewExpanded = ref(true)

  const fileReviewExpanded = ref(false)

  const fileReviewDrawer = ref(null)

  const assignmentDrawerCollapsedWidth = () => Math.min(window.innerWidth, Math.max(Math.min(720, window.innerWidth), window.innerWidth * DRAWER_COLLAPSED_RATIO))

  const assignmentDrawerAnimating = ref(false)

  let assignmentDrawerAnimationTimer

  const toggleAssignmentDrawerExpanded = () => {
    clearTimeout(assignmentDrawerAnimationTimer)
    assignmentDrawerAnimating.value = true
    if (assignmentDrawerExpanded.value) {
      ctx.assignmentDrawerWidth.value = assignmentDrawerCollapsedWidth()
      assignmentDrawerExpanded.value = false
    } else {
      ctx.assignmentDrawerWidth.value = window.innerWidth
      assignmentDrawerExpanded.value = true
    }
    assignmentDrawerAnimationTimer = setTimeout(() => { assignmentDrawerAnimating.value = false }, 220)
  }

  const resizeAssignmentDrawer = event => {
    const currentWidth = assignmentDrawerExpanded.value ? window.innerWidth : ctx.assignmentDrawerWidth.value
    assignmentDrawerExpanded.value = false
    ctx.startAssignmentDrawerResize(event, currentWidth)
  }

  const syncAssignmentDrawerToViewport = () => {
    if (assignmentDrawerExpanded.value) ctx.assignmentDrawerWidth.value = window.innerWidth
  }

  function updateFileReviewExpanded(value) {
    if (ctx.filePreview.mode === 'PEER') peerReviewExpanded.value = value
    else fileReviewExpanded.value = value
  }

  return { DRAWER_EXPANDED_STORAGE_KEY, DRAWER_COLLAPSED_RATIO, assignmentDrawerExpanded, peerReviewExpanded, fileReviewExpanded, fileReviewDrawer, assignmentDrawerCollapsedWidth, assignmentDrawerAnimating, assignmentDrawerAnimationTimer, toggleAssignmentDrawerExpanded, resizeAssignmentDrawer, syncAssignmentDrawerToViewport, updateFileReviewExpanded }
}
