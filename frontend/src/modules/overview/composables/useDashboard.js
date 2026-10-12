import { api } from '../../../api'
import { computed, ref } from 'vue'

export function useDashboard(ctx) {
  const dashboard = ref(null)

  const assignmentHistory = computed(() => dashboard.value?.assignment_history || [])

  const latestOverviewAssignment = computed(() => assignmentHistory.value.at(-1))

  const assignmentChartPoints = computed(() => {
    const items = assignmentHistory.value
    if (!items.length) return []
    const width = 920
    return items.map((item, index) => ({
      ...item,
      x: items.length === 1 ? width / 2 : 24 + index * (width - 48) / (items.length - 1),
      y: 18 + (100 - Number(item.completion_rate || 0)) * 1.64
    }))
  })

  const assignmentChartLine = computed(() => assignmentChartPoints.value.map(point => `${point.x},${point.y}`).join(' '))

  async function loadOverviewView(isCurrent, { background = false } = {}) {
      const dashboardData = await api(`/classes/${ctx.classId.value}/dashboard`)
      if (!isCurrent()) return
      dashboard.value = dashboardData
      if (ctx.role.value === 'STUDENT') {
        // 总览主体先展示，学生端的次要列表并行补齐，避免首屏等待四个接口。
        void Promise.allSettled([api(`/assignments?class_id=${ctx.classId.value}`), api(`/peer-review-assignments?class_id=${ctx.classId.value}`), api(`/grades?class_id=${ctx.classId.value}`), api(`/teams?class_id=${ctx.classId.value}`)]).then(([assignments, campaigns, grades, teams]) => {
          if (!isCurrent()) return
          if (assignments.status === 'fulfilled') { ctx.assignments.value = assignments.value.items }
          if (campaigns.status === 'fulfilled') { ctx.campaigns.value = campaigns.value.items }
          if (grades.status === 'fulfilled') { ctx.grades.value = grades.value.items }
          if (teams.status === 'fulfilled') { ctx.teams.value = teams.value.items }
        })
      }
    
  }

  return { dashboard, assignmentHistory, latestOverviewAssignment, assignmentChartPoints, assignmentChartLine, loadOverviewView }
}
