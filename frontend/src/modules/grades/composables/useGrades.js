import { api } from '../../../api'
import { computed, ref } from 'vue'

export function useGrades(ctx) {
  const grades = ref([])

  const gradeAssignments = ref([])

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
      const gradeData = ctx.role.value === 'TEACHER' ? await api(`/grades/assignments?class_id=${ctx.classId.value}`) : await api(`/grades?class_id=${ctx.classId.value}`)
      if (!isCurrent()) return
      if (ctx.role.value === 'TEACHER') gradeAssignments.value = gradeData.items
      else grades.value = gradeData.items
    
  }

  return { grades, gradeAssignments, selectedGradeAssignmentId, studentGradeSummary, studentLatestGrade, downloadExport, loadGradesView }
}
