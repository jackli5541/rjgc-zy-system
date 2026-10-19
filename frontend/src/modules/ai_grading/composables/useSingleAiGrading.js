import { ref } from 'vue'
import { api } from '../../../api'

// The owner resets this state whenever the drawer or submission changes.
export function useSingleAiGrading(getTarget) {
  const visible = ref(false)
  const loading = ref(false)
  const draft = ref(null)
  const error = ref('')
  const phase = ref('QUEUED')
  const animate = ref(false)
  let generation = 0
  let timer
  let deadlineTimer

  function reset() {
    generation += 1
    clearTimeout(timer)
    clearTimeout(deadlineTimer)
    visible.value = false
    loading.value = false
    draft.value = null
    error.value = ''
    phase.value = 'QUEUED'
    animate.value = false
  }

  async function start() {
    if (loading.value) return
    const target = getTarget()
    if (!target) return
    const current = ++generation
    clearTimeout(timer)
    visible.value = true
    loading.value = true
    draft.value = null
    error.value = ''
    phase.value = 'QUEUED'
    animate.value = false
    clearTimeout(deadlineTimer)
    deadlineTimer = setTimeout(() => {
      if (current !== generation) return
      generation += 1
      clearTimeout(timer)
      loading.value = false
      error.value = 'AI 批改等待超过 180 秒，请检查后台任务服务后重试'
    }, 180000)
    const path = `/assignments/${target.assignmentId}/submissions/${target.versionId}/ai-grading-draft`
    const isCurrent = () => {
      const latest = getTarget()
      return current === generation && latest?.assignmentId === target.assignmentId && latest?.versionId === target.versionId
    }
    async function request(initial) {
      try {
        const result = await api(initial ? `${path}/retry` : path, initial ? { method: 'POST' } : undefined)
        if (!isCurrent()) return
        const nextDraft = initial ? result : result.draft
        animate.value = !initial && nextDraft?.status === 'READY'
        draft.value = nextDraft
        phase.value = draft.value?.phase || 'QUEUED'
        if (draft.value?.status === 'PROCESSING') {
          timer = setTimeout(() => request(false), 750)
        } else {
          loading.value = false
          clearTimeout(deadlineTimer)
          if (draft.value?.status !== 'READY') error.value = draft.value?.error_message || 'AI 批改未完成，请重试'
        }
      } catch (requestError) {
        if (!isCurrent()) return
        error.value = requestError.message || 'AI 批改失败，请重试'
        loading.value = false
        clearTimeout(deadlineTimer)
      }
    }
    await request(true)
  }

  return { visible, loading, draft, error, phase, animate, start, reset }
}
