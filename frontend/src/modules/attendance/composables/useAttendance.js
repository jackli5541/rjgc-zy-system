import { computed, ref } from 'vue'
import { api } from '../../../api'

export function useAttendance(ctx) {
  const attendanceSessions = ref([])
  const selectedAttendance = ref(null)
  const attendanceOpen = ref(false)
  const activeAttendance = computed(() => attendanceSessions.value.find(item => ['ACTIVE', 'SCHEDULED'].includes(item.status)))

  async function loadAttendanceView(isCurrent = () => true) {
    if (ctx.role.value !== 'TEACHER') return
    const classId = ctx.classId.value
    const data = await api(`/classes/${classId}/attendance-sessions`)
    if (!isCurrent() || classId !== ctx.classId.value) return
    attendanceSessions.value = data.items
    const selectedId = selectedAttendance.value?.id
    const target = data.items.find(item => item.id === selectedId) || data.items[0]
    selectedAttendance.value = target ? await api(`/attendance-sessions/${target.id}`) : null
  }

  async function selectAttendance(id) {
    selectedAttendance.value = await api(`/attendance-sessions/${id}`)
  }

  return { attendanceSessions, selectedAttendance, activeAttendance, attendanceOpen, loadAttendanceView, selectAttendance }
}
