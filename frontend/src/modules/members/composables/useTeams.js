import { api, exportArchive } from '../../../api'
import { Modal, message } from 'ant-design-vue'
import { computed, reactive, ref } from 'vue'

export function useTeams(ctx) {
  const teams = ref([])

  const requests = ref([])

  const selectedTeam = ref(null)

  const selectedTeamAssignments = ref([])

  const teamCapstoneModules = ref({})

  const teamDrawerLoading = ref(false)

  const exportingTeamIds = reactive(new Set())

  let teamRequestGeneration = 0

  const teamForm = reactive({ name: '', open_recruitment: true })

  const topicForm = reactive({ name: '', description: '' })

  const topicDecisionForm = reactive({ id: '', reason: '' })

  const inviteTarget = ref('')

  const currentTeam = computed(() => teams.value.find(item => item.id === ctx.session.context?.team_membership?.team_id))

  const needsTopicSubmission = computed(() => Boolean(currentTeam.value?.is_leader && !currentTeam.value.topic))

  async function createTeam() {
    await ctx.action(async () => { await api('/teams', { method: 'POST', body: JSON.stringify({ class_id: ctx.classId.value, ...teamForm }) }); ctx.modals.team = false; await ctx.session.refreshContext(); await ctx.router.replace(ctx.session.landingPath) }, '小组已创建')
  }

  async function applyTeam(item) { await ctx.action(() => api(`/teams/${item.id}/applications`, { method: 'POST' }), '申请已提交') }

  async function cancelRequest(item) { await ctx.action(() => api(`/team-requests/${item.id}`, { method: 'DELETE' }), '申请已取消') }

  async function decideRequest(item, decision) { await ctx.action(() => api(`/team-requests/${item.id}/decision?decision=${decision}`, { method: 'POST' }), decision === 'APPROVED' ? '已同意申请' : '已拒绝申请') }

  async function openTeam(item) {
    const generation = ++teamRequestGeneration
    teamDrawerLoading.value = true
    selectedTeamAssignments.value = []
    try {
      selectedTeam.value = await api(`/teams/${item.id}`)
      topicForm.name = item.topic?.name || ''
      topicForm.description = item.topic?.description || ''
      if (item.is_leader || ctx.role.value === 'TEACHER') ctx.members.value = (await api(`/classes/${ctx.classId.value}/members`)).items
      try { teamCapstoneModules.value = (await api(`/capstone/classes/${ctx.classId.value}/teams/${item.id}/modules`)).modules || {} }
      catch (e) { teamCapstoneModules.value = {} }
      if (ctx.role.value === 'TEACHER') {
        const assignmentData = await api(`/assignments?class_id=${ctx.classId.value}`)
        const recentAssignments = assignmentData.items.filter(assignment => assignment.submitter_type === 'TEAM' && assignment.status !== 'DRAFT')
        const history = await Promise.all(recentAssignments.map(async assignment => {
          const board = await api(`/assignments/${assignment.id}/submissions`)
          const submission = board.items.find(record => record.team_id === item.id)
          return { ...assignment, submission: submission || { status: 'NOT_SUBMITTED', files: [] } }
        }))
        if (generation === teamRequestGeneration) selectedTeamAssignments.value = history
      }
    } catch (e) {
      if (generation === teamRequestGeneration) { selectedTeam.value = null; message.error(e.message) }
    } finally {
      if (generation === teamRequestGeneration) teamDrawerLoading.value = false
    }
  }

  function closeTeamDrawer() { teamRequestGeneration++; selectedTeam.value = null; selectedTeamAssignments.value = []; teamCapstoneModules.value = {}; teamDrawerLoading.value = false }

  async function saveTopic() { await ctx.action(async () => { await api(`/teams/${selectedTeam.value.id}/topic`, { method: 'POST', body: JSON.stringify(topicForm) }); selectedTeam.value = null }, '选题已提交审核') }

  async function saveTeamModuleName(memberId, value) {
    const moduleName = (value || '').trim()
    try {
      await api(`/capstone/classes/${ctx.classId.value}/students/${memberId}/module`, { method: 'PUT', body: JSON.stringify({ module_name: moduleName }) })
      teamCapstoneModules.value = { ...teamCapstoneModules.value, [memberId]: moduleName }
      message.success('模块名称已保存')
    } catch (e) { message.error(e.message || '保存失败') }
  }

  async function decideTopic(item, decision) {
    if (decision === 'REJECTED') { Object.assign(topicDecisionForm, { id: item.topic.id, reason: '' }); ctx.modals.topicDecision = true; return }
    await ctx.action(() => api(`/topics/${item.topic.id}/decision?decision=APPROVED`, { method: 'POST', body: JSON.stringify({ reason: '审核通过' }) }), '选题已通过')
    if (selectedTeam.value?.id === item.id) selectedTeam.value = await api(`/teams/${item.id}`)
  }

  async function rejectTopic() {
    if (!topicDecisionForm.reason.trim()) return message.warning('请填写驳回原因')
    const affectedTeamId = selectedTeam.value?.topic?.id === topicDecisionForm.id ? selectedTeam.value.id : null
    await ctx.action(async () => { await api(`/topics/${topicDecisionForm.id}/decision?decision=REJECTED`, { method: 'POST', body: JSON.stringify({ reason: topicDecisionForm.reason.trim() }) }); ctx.modals.topicDecision = false }, '选题已驳回')
    if (affectedTeamId) selectedTeam.value = await api(`/teams/${affectedTeamId}`)
  }

  async function inviteMember(item) {
    if (!inviteTarget.value) return
    await ctx.action(async () => {
      await api(`/teams/${item.id}/invitations`, { method: 'POST', body: JSON.stringify({ student_id: inviteTarget.value }) })
      inviteTarget.value = ''
    }, '邀请已发送')
  }

  async function respondInvitation(item, decision) { await ctx.action(() => api(`/team-requests/${item.id}/respond?decision=${decision}`, { method: 'POST' }), decision === 'APPROVED' ? '已加入小组' : '已拒绝邀请'); await ctx.session.refreshContext() }

  async function leaveTeam() { await ctx.action(async () => { await api(`/teams/${selectedTeam.value.id}/leave`, { method: 'POST' }); selectedTeam.value = null; await ctx.session.refreshContext(); await ctx.router.replace('/teams') }, '已退出小组') }

  function closeTeamRecruitment(item) {
    const teamId = item.id
    Modal.confirm({ title: '确认截止招募？', content: '所有待处理的入组申请和邀请将被取消。截止后不能邀请或加入，继续招募后需重新申请或邀请。', okText: '截止招募', onOk: () => ctx.action(async () => {
      const saved = await api(`/teams/${teamId}/close-recruitment`, { method: 'POST' })
      if (selectedTeam.value?.id === teamId) Object.assign(selectedTeam.value, saved)
    }, '已截止招募') })
  }

  async function openTeamRecruitment(item) {
    await ctx.action(async () => {
      const saved = await api(`/teams/${item.id}/open-recruitment`, { method: 'POST' })
      if (selectedTeam.value?.id === item.id) Object.assign(selectedTeam.value, saved)
    }, '已继续招募')
  }

  async function transferLeader(uid) { await ctx.action(async () => { await api(`/teams/${selectedTeam.value.id}/transfer`, { method: 'POST', body: JSON.stringify({ new_leader_id: uid }) }); selectedTeam.value = null }, '组长已移交') }

  function disbandTeam(item = selectedTeam.value) {
    if (!item) return
    const teamId = item.id
    const forcedByTeacher = ctx.role.value === 'TEACHER'
    Modal.confirm({
      title: forcedByTeacher ? `强制解散「${item.name}」？` : '确认解散小组？',
      content: forcedByTeacher ? '所有组员将变为未进入小组状态，已有作业与成绩记录仍会保留。' : '组员将重新进入组队流程。',
      okText: forcedByTeacher ? '强制解散' : '确认解散',
      okType: 'danger',
      onOk: () => ctx.action(async () => {
        await api(`/teams/${teamId}`, { method: 'DELETE' })
        if (selectedTeam.value?.id === teamId) closeTeamDrawer()
        if (!forcedByTeacher) {
          await ctx.session.refreshContext()
          await ctx.router.replace('/teams')
        }
      }, '小组已解散')
    })
  }

  async function downloadTeamCoursework(item) {
    if (!item || exportingTeamIds.has(item.id)) return
    exportingTeamIds.add(item.id)
    try {
      await exportArchive(`/teams/${item.id}/coursework.zip`)
      message.success('导出文件已生成')
    } catch (error) {
      message.warning(error.message || '当前无法导出，请稍后重试')
    } finally {
      exportingTeamIds.delete(item.id)
    }
  }

  async function loadTeamsView(isCurrent, { background = false } = {}) {
      const [t, r, memberData] = await Promise.all([api(`/teams?class_id=${ctx.classId.value}`), ctx.role.value === 'STUDENT' ? api(`/team-requests?class_id=${ctx.classId.value}`) : Promise.resolve({ items: [] }), ctx.role.value === 'TEACHER' ? api(`/classes/${ctx.classId.value}/members`) : Promise.resolve({ items: [] })])
      if (!isCurrent()) return
      teams.value = t.items; requests.value = r.items; ctx.members.value = memberData.items
      if (ctx.role.value === 'STUDENT' && teams.value.some(item => item.is_leader)) {
        const availableMembers = await api(`/classes/${ctx.classId.value}/members`)
        if (!isCurrent()) return
        ctx.members.value = availableMembers.items
      }
      const linkedTeam = teams.value.find(item => item.id === ctx.route.query.team)
      if (linkedTeam) await openTeam(linkedTeam)
    
  }

  return { teams, requests, selectedTeam, selectedTeamAssignments, teamCapstoneModules, teamDrawerLoading, exportingTeamIds, teamRequestGeneration, teamForm, topicForm, topicDecisionForm, inviteTarget, currentTeam, needsTopicSubmission, createTeam, applyTeam, cancelRequest, decideRequest, openTeam, closeTeamDrawer, saveTopic, saveTeamModuleName, decideTopic, rejectTopic, inviteMember, respondInvitation, leaveTeam, closeTeamRecruitment, openTeamRecruitment, transferLeader, disbandTeam, downloadTeamCoursework, loadTeamsView }
}
