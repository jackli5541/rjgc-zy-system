import { api } from '../../../api'
import { computed, ref } from 'vue'

export function useGrades(ctx) {
  const grades = ref([])

  const gradeAssignments = ref([])
  const overviewItems = ref([])
  const overviewLoading = ref(false)
  const gradeAssignmentsLoading = ref(false)
  let loadGeneration = 0
  let loadedClassId = null

  const selectedGradeAssignmentId = ref('')

  const studentGradeSummary = computed(() => {
    return { count: grades.value.length, average: grades.value[0]?.final_grade || '-' }
  })

  const studentLatestGrade = computed(() => grades.value[0])

  function downloadExport(kind, format = 'xlsx') {
    const assignment = kind === 'grades' && selectedGradeAssignmentId.value ? `&assignment_id=${selectedGradeAssignmentId.value}` : ''
    window.location.href = `/api/v1/exports/${kind}.${format}?class_id=${ctx.classId.value}${assignment}`
  }

  async function loadGradesView(isCurrent, { background = false } = {}) {
    const generation = ++loadGeneration
    const classId = ctx.classId.value
    const teacher = ctx.role.value === 'TEACHER'
    const current = () => generation === loadGeneration && isCurrent()
    if (!teacher) {
      const data = await api(`/grades?class_id=${classId}`)
      if (current()) grades.value = data.items
      return
    }
    if (loadedClassId !== classId) {
      overviewItems.value = []
      gradeAssignments.value = []
      selectedGradeAssignmentId.value = ''
      loadedClassId = classId
    }
    overviewLoading.value = true
    gradeAssignmentsLoading.value = true
    ctx.loadedViewKeys.add(ctx.pageKey.value)
    const load = async (path, items, busy) => {
      try {
        const data = await api(path)
        if (current()) items.value = data.items
      } finally {
        if (generation === loadGeneration) busy.value = false
      }
    }
    const results = await Promise.allSettled([
      load(`/grades/assignments?class_id=${classId}`, gradeAssignments, gradeAssignmentsLoading),
      load(`/classes/${classId}/grade-overview`, overviewItems, overviewLoading)
    ])
    const failure = results.find(result => result.status === 'rejected')
    if (current() && failure) throw failure.reason
  }

  return { grades, gradeAssignments, gradeAssignmentsLoading, overviewItems, overviewLoading, selectedGradeAssignmentId, studentGradeSummary, studentLatestGrade, downloadExport, loadGradesView }
}
