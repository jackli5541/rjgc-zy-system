import { computed, onScopeDispose, ref, watch } from 'vue'
import { recentCheckedInRecords } from '../records.js'

export function useProjectionFeedback(selectedAttendance, projecting) {
  const newcomers = ref([])
  const feedbackKey = ref(0)
  const completed = ref(false)
  let seen = new Set()
  let timer
  const highlightedIds = computed(() => new Set(newcomers.value.map(record => record.student_id)))
  const feedbackText = computed(() => {
    const records = newcomers.value
    if (completed.value) return '全员签到完成！'
    if (records.length === 1) return `${records[0].student_name} ${records[0].status === 'LATE' ? '已签到 · 迟到' : '签到成功'}`
    if (records.length <= 3) return `${records.map(record => record.student_name).join('、')} 已签到`
    return `新增 ${records.length} 人签到`
  })

  function clearFeedback() {
    clearTimeout(timer)
    newcomers.value = []
    completed.value = false
  }

  watch(() => ({
    open: projecting.value && selectedAttendance.value?.status === 'ACTIVE',
    id: selectedAttendance.value?.id,
    total: selectedAttendance.value?.total || 0,
    records: recentCheckedInRecords(selectedAttendance.value?.records),
  }), (current, previous) => {
    if (!current.open || !previous?.open || current.id !== previous.id) {
      clearFeedback()
      seen = new Set(current.records.map(record => record.student_id))
      return
    }
    const added = current.records.filter(record => record.checked_in_at && !seen.has(record.student_id))
    current.records.forEach(record => seen.add(record.student_id))
    if (!added.length) return
    clearFeedback()
    newcomers.value = added
    completed.value = current.total > 0 && current.records.length === current.total && previous.records.length < current.total
    feedbackKey.value += 1
    timer = setTimeout(clearFeedback, 3000)
  }, { immediate: true })

  onScopeDispose(clearFeedback)
  return { newcomers, highlightedIds, feedbackText, feedbackKey, completed }
}
