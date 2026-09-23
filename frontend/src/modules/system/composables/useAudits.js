import { api } from '../../../api'
import { computed, ref } from 'vue'

export function useAudits(ctx) {
  const audits = ref([])

  const auditSearch = ref('')

  const auditSemester = ref('ALL')

  const auditClassId = ref('ALL')

  const auditActorRole = ref('ALL')

  const auditSearched = ref(false)

  const auditPage = ref(1)

  const auditPageSize = 10

  const auditTotal = ref(0)

  const auditSemesterOptions = computed(() => [...new Set(ctx.session.classes.map(item => item.semester))].sort().map(value => ({ value, label: value })))

  const auditClassOptions = computed(() => ctx.session.classes.filter(item => auditSemester.value === 'ALL' || item.semester === auditSemester.value).map(item => ({ value: item.id, label: item.name })))

  function auditSearchParams() {
    const params = new URLSearchParams()
    const query = auditSearch.value.trim()
    if (query) {
      params.set('q', query)
      Object.entries(ctx.actionLabels).filter(([, label]) => label.includes(query)).forEach(([value]) => params.append('actions', value))
      Object.entries(ctx.objectLabels).filter(([, label]) => label.includes(query)).forEach(([value]) => params.append('object_types', value))
    }
    if (auditSemester.value !== 'ALL') params.set('semester', auditSemester.value)
    if (auditClassId.value !== 'ALL') params.set('class_id', auditClassId.value)
    if (auditActorRole.value !== 'ALL') params.set('actor_role', auditActorRole.value)
    return params
  }

  async function searchAudits() {
    auditSearched.value = true
    auditPage.value = 1
    await ctx.loadView()
  }

  async function changeAuditSemester() {
    if (!auditClassOptions.value.some(item => item.value === auditClassId.value)) auditClassId.value = 'ALL'
    await searchAudits()
  }

  async function changeAuditPage(page) { auditPage.value = page; await ctx.loadView({ silent: true }) }

  async function loadAuditsView(isCurrent, { background = false } = {}) {
    if (!(ctx.role.value === 'TEACHER')) return
      if (!auditSearched.value) {
        audits.value = []
        auditTotal.value = 0
        return
      }
      const params = auditSearchParams()
      params.set('page', auditPage.value)
      params.set('page_size', auditPageSize)
      const auditData = await api(`/audit-logs?${params}`)
      if (!isCurrent()) return
      audits.value = auditData.items
      auditTotal.value = auditData.total
    
  }

  return { audits, auditSearch, auditSemester, auditClassId, auditActorRole, auditSearched, auditPage, auditPageSize, auditTotal, auditSemesterOptions, auditClassOptions, auditSearchParams, searchAudits, changeAuditSemester, changeAuditPage, loadAuditsView }
}
