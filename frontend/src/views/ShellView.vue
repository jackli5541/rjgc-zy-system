<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { BellOutlined, BookOutlined, CheckCircleOutlined, CloseOutlined, CodeOutlined, DashboardOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, EyeOutlined, FileTextOutlined, FormOutlined, InboxOutlined, KeyOutlined, LogoutOutlined, PlusOutlined, RedoOutlined, SettingOutlined, TeamOutlined, TrophyOutlined, UploadOutlined, UserOutlined } from '@ant-design/icons-vue'
import { api } from '../api'
import { useSessionStore } from '../stores/session'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const dashboard = ref(null)
const teams = ref([])
const requests = ref([])
const members = ref([])
const memberDetail = ref(null)
const memberQuery = ref('')
const memberSaving = ref(false)
const assignments = ref([])
const campaigns = ref([])
const grades = ref([])
const gradeRevisions = ref([])
const selectedGrade = ref(null)
const notifications = ref([])
const audits = ref([])
const selectedTeam = ref(null)
const selectedAssignment = ref(null)
const selectedCampaign = ref(null)
const candidates = ref([])
const campaignStats = ref(null)
const campaignReviews = ref([])
const receivedReviews = ref([])
const sentReviews = ref([])
const classJoinRequests = ref([])
const assignmentAttachments = ref([])
const pendingAssignmentFiles = ref([])
const draftFiles = ref([])
const selectedFileIds = ref([])
const boardFilter = ref('ALL')
const boardQuery = ref('')
const noticesOpen = ref(false)
const campaignOptionsLoading = ref(false)
const campaignAssignmentsByClass = reactive({})
const campaignAssignmentIds = reactive({})
const modals = reactive({ class: false, import: false, member: false, team: false, assignment: false, campaign: false, review: false, grade: false, password: false, invalidate: false, joinClass: false, topicDecision: false })
const classForm = reactive({ id: '', version: 1, semester: '', name: '', team_deadline: '', max_team_members: 5, topic_public: false, invite_requires_approval: true })
const joinClassForm = reactive({ invite_code: '' })
const memberForm = reactive({ id: '', student_no: '', name: '' })
const teamForm = reactive({ name: '', open_recruitment: true })
const assignmentForm = reactive({ id: '', version: 1, has_submissions: false, class_ids: [], title: '', description: '', submitter_type: 'INDIVIDUAL', starts_at: '', due_at: '', allow_late: false, publish: true })
const campaignForm = reactive({ id: '', version: 1, has_reviews: false, class_ids: [], publish_at: '', due_at: '', comment_min_length: 20, require_all: false, allow_update: true })
const rubric = ref([{ label: '', weight: 100 }])
const reviewForm = reactive({ reviewee_id: '', scores: {}, comment: '' })
const selectedReview = ref(null)
const invalidReason = ref('')
const topicForm = reactive({ name: '', description: '' })
const topicDecisionForm = reactive({ id: '', reason: '' })
const passwordForm = reactive({ current_password: '', new_password: '' })
const gradeForm = reactive({ assignment_id: '', subject_user_id: '', subject_team_id: '', score: 0, comment: '', publish: false, reason: '' })
const inviteTarget = ref('')
const importState = reactive({ file: null, preview: null, result: null, step: 0, loading: false })
let gateTimer

const role = computed(() => session.user?.role)
const classId = computed(() => session.classId)
const view = computed(() => route.params.view || 'overview')
const activeClasses = computed(() => session.classes.filter(item => item.status === 'ACTIVE'))
const classOptions = computed(() => activeClasses.value.map(item => ({ value: item.id, label: `${item.semester} · ${item.name}` })))
const currentTeam = computed(() => teams.value.find(item => item.id === session.context?.team_membership?.team_id))
const gradeAssignment = computed(() => assignments.value.find(item => item.id === gradeForm.assignment_id))
const filteredMembers = computed(() => {
  const query = memberQuery.value.trim().toLocaleLowerCase()
  return members.value.filter(item => {
    const matchesQuery = !query || `${item.student_no} ${item.name} ${item.team || ''}`.toLocaleLowerCase().includes(query)
    return matchesQuery
  })
})
const filteredBoard = computed(() => (selectedAssignment.value?.board || []).filter(item => {
  const q = boardQuery.value.trim().toLocaleLowerCase()
  const matchesQuery = !q || `${item.owner || ''} ${item.team_name || ''}`.toLocaleLowerCase().includes(q)
  const matchesStatus = boardFilter.value === 'ALL' || (boardFilter.value === 'LATE' ? item.is_late : boardFilter.value === item.status)
  return matchesQuery && matchesStatus
}))
const studentGradeSummary = computed(() => {
  const published = grades.value.filter(item => item.status === 'PUBLISHED')
  const average = published.length ? (published.reduce((sum, item) => sum + Number(item.score || 0), 0) / published.length).toFixed(1) : '-'
  return { count: published.length, average }
})
const studentPendingAssignments = computed(() => assignments.value.filter(item => item.status === 'PUBLISHED' && item.submission_status !== 'SUBMITTED'))
const studentUpcomingAssignments = computed(() => {
  const limit = Date.now() + 72 * 60 * 60 * 1000
  return studentPendingAssignments.value.filter(item => new Date(item.due_at).getTime() <= limit && new Date(item.due_at).getTime() >= Date.now())
})
const studentPendingReviews = computed(() => campaigns.value.reduce((total, item) => total + Number(item.pending_count || 0), 0))
const studentLatestGrade = computed(() => grades.value.find(item => item.status === 'PUBLISHED'))
const gradePublishPreview = computed(() => {
  const assignment = gradeAssignment.value
  if (!assignment) return null
  const records = grades.value.filter(item => item.assignment_id === assignment.id)
  const total = assignment.submitter_type === 'TEAM' ? teams.value.length : members.value.length
  const scores = records.map(item => Number(item.score)).filter(Number.isFinite)
  return { assignment: assignment.title, scored: records.length, pending: Math.max(total - records.length, 0), range: scores.length ? `${Math.min(...scores)} - ${Math.max(...scores)} 分` : '暂无已评分记录' }
})
const menu = computed(() => {
  if (role.value === 'TEACHER') return [
    ['overview', DashboardOutlined, '总览'], ['classes', BookOutlined, '教学班'], ['teams', TeamOutlined, '小组与选题'],
    ['assignments', FileTextOutlined, '作业管理'], ['reviews', FormOutlined, '互评管理'], ['grades', TrophyOutlined, '成绩与导出'], ['system', SettingOutlined, '系统与审计']
  ]
  if (session.teamGate) return [['teams', TeamOutlined, '加入小组']]
  return [['overview', DashboardOutlined, '总览'], ['teams', TeamOutlined, '我的小组'], ['assignments', FileTextOutlined, '我的作业'], ['reviews', FormOutlined, '作品互评'], ['grades', TrophyOutlined, '成绩与反馈']]
})

function iso(value) { return value ? new Date(value).toISOString() : null }
function localDateTime(value) { if (!value) return ''; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-' }
const statusLabels = { ACTIVE: '进行中', ARCHIVED: '已归档', PENDING: '待处理', APPROVED: '已通过', REJECTED: '已拒绝', CANCELLED: '已取消', DRAFT: '草稿', PUBLISHED: '已发布', SUBMITTED: '已提交', RETRACTED: '已撤回', VALID: '有效', INVALID: '已作废', CLOSED: '已结束', NOT_SUBMITTED: '未提交', LEFT: '已退出', DISBANDED: '已解散', NOT_STARTED: '未开始' }
const roleLabels = { LEADER: '组长', MEMBER: '组员', TEACHER: '教师', STUDENT: '学生' }
const objectLabels = { user: '用户', class: '教学班', class_join_request: '入班申请', team: '小组', team_request: '组队申请', topic: '选题', assignment: '作业', submission: '作业提交', review_campaign: '互评活动', peer_review: '作品评价', grade: '成绩' }
const actionLabels = { PASSWORD_CHANGED: '修改密码', PASSWORD_RESET: '重置密码', CLASS_CREATED: '创建教学班', CLASS_UPDATED: '更新教学班', CLASS_DELETED: '删除教学班', CLASS_JOIN_REQUESTED: '申请加入教学班', CLASS_JOINED_BY_INVITE: '通过邀请码入班', CLASS_JOIN_APPROVED: '同意入班申请', CLASS_JOIN_REJECTED: '拒绝入班申请', ROSTER_IMPORTED: '导入学生名单', CLASS_MEMBER_ADDED: '添加班级成员', CLASS_MEMBER_UPDATED: '更新成员信息', CLASS_MEMBER_REMOVED: '移出班级成员', TEAM_CREATED: '创建小组', TEAM_REQUEST_DECIDED: '处理组队申请', TEAM_INVITATION_RESPONDED: '回应小组邀请', TEAM_LEADER_TRANSFERRED: '移交组长', TEAM_LEFT: '退出小组', TEAM_DISBANDED: '解散小组', TEAM_MEMBER_REMOVED: '移出小组成员', TOPIC_SUBMITTED: '提交选题', TOPIC_DECIDED: '审核选题', ASSIGNMENT_CREATED: '创建作业', ASSIGNMENT_UPDATED: '更新作业', ASSIGNMENT_PUBLISHED: '发布作业', SUBMISSION_CREATED: '提交作业', SUBMISSION_RETRACTED: '撤回作业', SUBMISSIONS_EXPORTED: '导出作业', REVIEW_CAMPAIGN_CREATED: '创建互评活动', PEER_REVIEW_SUBMITTED: '提交作品评价', PEER_REVIEW_INVALIDATED: '作废作品评价', GRADE_SAVED: '保存成绩' }
function statusLabel(value) { return statusLabels[value] || value || '-' }
function roleLabel(value) { return roleLabels[value] || value || '-' }
function objectLabel(value) { return objectLabels[value] || value || '-' }
function actionLabel(value) { return actionLabels[value] || value || '-' }
async function action(fn, success) { try { await fn(); if (success) message.success(success); await loadView() } catch (e) { message.error(e.message) } }

async function loadCommon() {
  if (!classId.value) { notifications.value = []; return }
  const [noticeData] = await Promise.all([api('/notifications')])
  notifications.value = noticeData.items
}

async function loadView() {
  loading.value = true
  try {
    await loadCommon()
    if (!classId.value) return
    if (view.value === 'overview') {
      dashboard.value = await api(`/classes/${classId.value}/dashboard`)
      if (role.value === 'STUDENT') {
        const [assignmentData, campaignData, gradeData, teamData] = await Promise.all([api(`/assignments?class_id=${classId.value}`), api(`/review-campaigns?class_id=${classId.value}`), api(`/grades?class_id=${classId.value}`), api(`/teams?class_id=${classId.value}`)])
        assignments.value = assignmentData.items; campaigns.value = campaignData.items; grades.value = gradeData.items; teams.value = teamData.items
      }
    }
    if (view.value === 'classes') {
      const [memberData, requestData] = await Promise.all([api(`/classes/${classId.value}/members`), role.value === 'TEACHER' ? api(`/classes/${classId.value}/join-requests`) : Promise.resolve({ items: [] })])
      members.value = memberData.items; classJoinRequests.value = requestData.items
    }
    if (view.value === 'teams') {
      const [t, r] = await Promise.all([api(`/teams?class_id=${classId.value}`), api(`/team-requests?class_id=${classId.value}`)])
      teams.value = t.items; requests.value = r.items
    }
    if (view.value === 'assignments') assignments.value = (await api(`/assignments?class_id=${classId.value}`)).items
    if (view.value === 'reviews') {
      campaigns.value = (await api(`/review-campaigns?class_id=${classId.value}`)).items
      if (role.value === 'TEACHER') assignments.value = (await api(`/assignments?class_id=${classId.value}`)).items
      if (role.value === 'STUDENT') { const [received, sent] = await Promise.all([api(`/peer-reviews/received?class_id=${classId.value}`), api(`/peer-reviews/sent?class_id=${classId.value}`)]); receivedReviews.value = received.items; sentReviews.value = sent.items }
    }
    if (view.value === 'grades') {
      grades.value = (await api(`/grades?class_id=${classId.value}`)).items
      if (role.value === 'TEACHER') {
        const [assignmentData, memberData, teamData] = await Promise.all([api(`/assignments?class_id=${classId.value}`), api(`/classes/${classId.value}/members`), api(`/teams?class_id=${classId.value}`)])
        assignments.value = assignmentData.items; members.value = memberData.items; teams.value = teamData.items
      }
    }
    if (view.value === 'system' && role.value === 'TEACHER') audits.value = (await api('/audit-logs')).items
  } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}

async function changeClass(id) { await session.refreshClasses(id); await router.replace(session.teamGate ? '/teams' : '/overview'); await loadView() }
async function manageClass(item) { await session.refreshClasses(item.id); await router.replace('/classes'); await loadView() }
function openClassCreate() {
  Object.assign(classForm, { id: '', version: 1, semester: '', name: '', team_deadline: '', max_team_members: 5, topic_public: false, invite_requires_approval: true }); modals.class = true
}
function openClassEdit(item) {
  Object.assign(classForm, { id: item.id, version: item.version, semester: item.semester, name: item.name, team_deadline: localDateTime(item.team_deadline), max_team_members: item.max_team_members, topic_public: item.topic_public, invite_requires_approval: item.invite_requires_approval }); modals.class = true
}
async function saveClass() {
  if (!classForm.semester.trim() || !classForm.name.trim()) return message.warning('请填写学期和班级名称')
  const payload = { semester: classForm.semester, name: classForm.name, team_deadline: iso(classForm.team_deadline), max_team_members: classForm.max_team_members, topic_public: classForm.topic_public, invite_requires_approval: classForm.invite_requires_approval }
  const editing = Boolean(classForm.id)
  await action(async () => {
    const saved = editing
      ? await api(`/classes/${classForm.id}`, { method: 'PATCH', body: JSON.stringify({ ...payload, version: classForm.version }) })
      : await api('/classes', { method: 'POST', body: JSON.stringify(payload) })
    modals.class = false; await session.refreshClasses(saved.id)
  }, editing ? '教学班资料已更新' : '教学班已创建')
}
async function joinClass() {
  if (!joinClassForm.invite_code.trim()) return message.warning('请输入邀请码')
  await action(async () => {
    const result = await api('/classes/join', { method: 'POST', body: JSON.stringify({ invite_code: joinClassForm.invite_code }) })
    joinClassForm.invite_code = ''; modals.joinClass = false
    if (result.status === 'APPROVED') await session.refreshClasses(result.class_id)
  }, '已提交教学班加入申请')
}
async function decideClassJoin(item, decision) {
  await action(() => api(`/classes/${classId.value}/join-requests/${item.id}/decision?decision=${decision}`, { method: 'POST' }), decision === 'APPROVED' ? '已同意加入教学班' : '已拒绝加入申请')
}
async function toggleClassStatus(item) {
  const status = item.status === 'ACTIVE' ? 'ARCHIVED' : 'ACTIVE'
  await action(async () => {
    await api(`/classes/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status, version: item.version }) })
    await session.refreshClasses(classId.value)
  }, status === 'ARCHIVED' ? '教学班已归档' : '教学班已恢复')
}
function deleteClass(item) {
  Modal.confirm({
    title: `删除教学班“${item.name}”？`, content: '仅无名单、成员、小组和作业记录的空班可以删除。', okText: '确认删除', okType: 'danger',
    onOk: () => action(async () => {
      await api(`/classes/${item.id}`, { method: 'DELETE' })
      const fallback = item.id === classId.value ? session.classes.find(course => course.id !== item.id)?.id : classId.value
      await session.refreshClasses(fallback)
    }, '教学班已删除')
  })
}
function chooseRoster(file) { importState.file = file; importState.preview = null; importState.result = null; importState.step = 0; return false }
async function previewRoster() {
  if (!importState.file) return message.warning('请选择名单文件')
  importState.loading = true
  try { const body = new FormData(); body.append('file', importState.file); importState.preview = await api(`/classes/${classId.value}/members/import-preview`, { method: 'POST', body }); importState.step = 1 }
  catch (e) { message.error(e.message) } finally { importState.loading = false }
}
async function confirmRoster() {
  try {
    importState.loading = true
    importState.result = await api(`/classes/${classId.value}/members/import/${importState.preview.batch_id}/confirm`, { method: 'POST' })
    importState.step = 2; message.success(`已创建 ${importState.result.created} 个账号，加入 ${importState.result.joined} 名学生`)
    members.value = (await api(`/classes/${classId.value}/members`)).items
  } catch (e) { message.error(e.message) } finally { importState.loading = false }
}
function closeImport() { modals.import = false; Object.assign(importState, { file: null, preview: null, result: null, step: 0, loading: false }) }
function openMemberCreate() { Object.assign(memberForm, { id: '', student_no: '', name: '' }); modals.member = true }
function openMemberEdit(item) { Object.assign(memberForm, { id: item.id, student_no: item.student_no, name: item.name }); modals.member = true }
async function openMemberDetail(item) {
  try { memberDetail.value = await api(`/classes/${classId.value}/members/${item.id}`) }
  catch (e) { message.error(e.message) }
}
async function saveMember() {
  if (!memberForm.student_no.trim() || !memberForm.name.trim()) return message.warning('请填写学号和姓名')
  memberSaving.value = true
  try {
    if (memberForm.id) await api(`/classes/${classId.value}/members/${memberForm.id}`, { method: 'PATCH', body: JSON.stringify({ name: memberForm.name }) })
    else await api(`/classes/${classId.value}/members`, { method: 'POST', body: JSON.stringify({ student_no: memberForm.student_no, name: memberForm.name }) })
    modals.member = false; message.success(memberForm.id ? '成员信息已更新' : '成员已添加'); await loadView()
  } catch (e) { message.error(e.message) } finally { memberSaving.value = false }
}
function resetMemberPassword(item) { Modal.confirm({ title: `重置 ${item.name} 的密码？`, content: '密码将重置为当前学号。', okText: '确认重置', onOk: () => action(() => api(`/classes/${classId.value}/members/${item.id}/reset-password`, { method: 'POST' }), '密码已重置') }) }
function removeClassMember(item) { Modal.confirm({ title: `将 ${item.name} 移出教学班？`, content: item.team ? `该成员也会退出小组「${item.team}」。` : '历史提交和成绩将继续保留。', okText: '确认移出', okType: 'danger', onOk: () => action(() => api(`/classes/${classId.value}/members/${item.id}`, { method: 'DELETE' }), '成员已移出') }) }
async function createTeam() {
  await action(async () => { await api('/teams', { method: 'POST', body: JSON.stringify({ class_id: classId.value, ...teamForm }) }); modals.team = false; await session.refreshContext(); await router.replace('/overview') }, '小组已创建')
}
async function applyTeam(item) { await action(() => api(`/teams/${item.id}/applications`, { method: 'POST' }), '申请已提交') }
async function cancelRequest(item) { await action(() => api(`/team-requests/${item.id}`, { method: 'DELETE' }), '申请已取消') }
async function decideRequest(item, decision) { await action(() => api(`/team-requests/${item.id}/decision?decision=${decision}`, { method: 'POST' }), decision === 'APPROVED' ? '已同意申请' : '已拒绝申请') }
async function openTeam(item) { selectedTeam.value = await api(`/teams/${item.id}`); topicForm.name = item.topic?.name || ''; topicForm.description = item.topic?.description || ''; if (item.is_leader || role.value === 'TEACHER') members.value = (await api(`/classes/${classId.value}/members`)).items }
async function saveTopic() { await action(async () => { await api(`/teams/${selectedTeam.value.id}/topic`, { method: 'POST', body: JSON.stringify(topicForm) }); selectedTeam.value = null }, '选题已提交审核') }
async function decideTopic(item, decision) {
  if (decision === 'REJECTED') { Object.assign(topicDecisionForm, { id: item.topic.id, reason: '' }); modals.topicDecision = true; return }
  await action(() => api(`/topics/${item.topic.id}/decision?decision=APPROVED`, { method: 'POST', body: JSON.stringify({ reason: '审核通过' }) }), '选题已通过')
}
async function rejectTopic() {
  if (!topicDecisionForm.reason.trim()) return message.warning('请填写驳回原因')
  await action(async () => { await api(`/topics/${topicDecisionForm.id}/decision?decision=REJECTED`, { method: 'POST', body: JSON.stringify({ reason: topicDecisionForm.reason.trim() }) }); modals.topicDecision = false }, '选题已驳回')
}
async function inviteMember() { await action(() => api(`/teams/${selectedTeam.value.id}/invitations`, { method: 'POST', body: JSON.stringify({ student_id: inviteTarget.value }) }), '邀请已发送'); inviteTarget.value = '' }
async function respondInvitation(item, decision) { await action(() => api(`/team-requests/${item.id}/respond?decision=${decision}`, { method: 'POST' }), decision === 'APPROVED' ? '已加入小组' : '已拒绝邀请'); await session.refreshContext() }
async function leaveTeam() { await action(async () => { await api(`/teams/${selectedTeam.value.id}/leave`, { method: 'POST' }); selectedTeam.value = null; await session.refreshContext(); await router.replace('/teams') }, '已退出小组') }
async function transferLeader(uid) { await action(async () => { await api(`/teams/${selectedTeam.value.id}/transfer`, { method: 'POST', body: JSON.stringify({ new_leader_id: uid }) }); selectedTeam.value = null }, '组长已移交') }
function disbandTeam() { Modal.confirm({ title: '确认解散小组？', content: '组员将重新进入组队流程。', okText: '确认解散', okType: 'danger', onOk: () => action(async () => { await api(`/teams/${selectedTeam.value.id}`, { method: 'DELETE' }); selectedTeam.value = null; await session.refreshContext(); await router.replace('/teams') }, '小组已解散') }) }
function removeTeamMember(member) { Modal.confirm({ title: `将 ${member.name} 移出小组？`, okText: '确认移出', okType: 'danger', onOk: () => action(async () => { await api(`/teams/${selectedTeam.value.id}/members/${member.id}`, { method: 'DELETE' }); selectedTeam.value = null }, '成员已移出') }) }
function defaultClassSelection() {
  if (activeClasses.value.some(item => item.id === classId.value)) return [classId.value]
  return activeClasses.value[0] ? [activeClasses.value[0].id] : []
}
function openAssignmentCreate() {
  Object.assign(assignmentForm, { id: '', version: 1, has_submissions: false, class_ids: defaultClassSelection(), title: '', description: '', submitter_type: 'INDIVIDUAL', starts_at: '', due_at: '', allow_late: false, publish: true }); pendingAssignmentFiles.value = []; modals.assignment = true
}
function openAssignmentEdit() {
  const item = selectedAssignment.value
  Object.assign(assignmentForm, { id: item.id, version: item.version, has_submissions: (item.board || []).some(record => record.version_no > 0), class_ids: [item.class_id], title: item.title, description: item.description, submitter_type: item.submitter_type, starts_at: localDateTime(item.starts_at), due_at: localDateTime(item.due_at), allow_late: item.allow_late, publish: item.status === 'PUBLISHED' })
  selectedAssignment.value = null; pendingAssignmentFiles.value = []; modals.assignment = true
}
function queueAssignmentAttachment(file) { pendingAssignmentFiles.value.push(file); return false }
function removePendingAssignmentAttachment(index) { pendingAssignmentFiles.value.splice(index, 1) }
async function createAssignment() {
  if (!assignmentForm.id && !assignmentForm.class_ids.length) return message.warning('请至少选择一个教学班')
  if (!assignmentForm.due_at) return message.warning('请选择截止时间')
  if (assignmentForm.starts_at && new Date(assignmentForm.starts_at) >= new Date(assignmentForm.due_at)) return message.warning('开始时间必须早于截止时间')
  if (assignmentForm.id) {
    await action(async () => {
      const payload = { title: assignmentForm.title, description: assignmentForm.description, submitter_type: assignmentForm.submitter_type, starts_at: iso(assignmentForm.starts_at), due_at: iso(assignmentForm.due_at), allow_late: assignmentForm.allow_late, version: assignmentForm.version }
      await api(`/assignments/${assignmentForm.id}`, { method: 'PATCH', body: JSON.stringify(payload) }); modals.assignment = false
    }, '作业已更新')
    return
  }
  const count = assignmentForm.class_ids.length
  try {
    const created = await api('/assignments/bulk', { method: 'POST', body: JSON.stringify({ ...assignmentForm, starts_at: iso(assignmentForm.starts_at), due_at: iso(assignmentForm.due_at) }) })
    const failed = []
    for (const assignment of created.items) {
      for (const file of pendingAssignmentFiles.value) {
        try {
          const body = new FormData(); body.append('file', file)
          await api(`/assignments/${assignment.id}/files`, { method: 'POST', body })
        } catch (error) { failed.push(`${assignment.title}：${file.name}（${error.message}）`) }
      }
    }
    pendingAssignmentFiles.value = []; modals.assignment = false; await session.refreshClasses(classId.value); await loadView()
    message.success(assignmentForm.publish ? `已向 ${count} 个教学班发布作业` : `已为 ${count} 个教学班保存草稿`)
    if (failed.length) message.warning(`作业已创建，但有 ${failed.length} 个附件上传失败`)
  } catch (error) { message.error(error.message) }
}
async function openAssignment(item) {
  selectedAssignment.value = item; selectedFileIds.value = []; boardFilter.value = 'ALL'; boardQuery.value = ''
  const files = await api(`/assignments/${item.id}/files`); assignmentAttachments.value = files.attachments; draftFiles.value = files.drafts
  if (role.value === 'STUDENT') item.submission = await api(`/assignments/${item.id}/submission`)
  else item.board = (await api(`/assignments/${item.id}/submissions`)).items
}
async function uploadFile({ file, onSuccess, onError }) {
  try {
    const body = new FormData(); body.append('file', file); const saved = await api(`/assignments/${selectedAssignment.value.id}/files`, { method: 'POST', body })
    if (role.value === 'TEACHER') assignmentAttachments.value.push(saved)
    else { draftFiles.value.push(saved); selectedFileIds.value.push(saved.id) }
    onSuccess(saved)
  } catch (e) { onError(e); message.error(e.message) }
}
function deleteDraft(file) { Modal.confirm({ title: '确认删除文件？', content: '删除后无法恢复。', okText: '确认删除', cancelText: '取消', onOk: () => action(async () => { await api(`/files/${file.id}`, { method: 'DELETE' }); await openAssignment(selectedAssignment.value) }, '文件已删除') }) }
async function submitAssignment() {
  if (!selectedFileIds.value.length) return message.warning('请选择本次提交文件')
  Modal.confirm({ title: '确认正式提交？', content: '正式提交会生成不可覆盖的新版本。', okText: '确认提交', cancelText: '继续检查', onOk: async () => action(async () => { await api(`/assignments/${selectedAssignment.value.id}/submission`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ file_ids: selectedFileIds.value }) }); selectedAssignment.value = null }, '提交成功') })
}
async function publishAssignment() { await action(async () => { await api(`/assignments/${selectedAssignment.value.id}/publish`, { method: 'POST' }); selectedAssignment.value = null }, '作业已发布') }
async function retractAssignment() { await action(async () => { await api(`/assignments/${selectedAssignment.value.id}/submission/retract`, { method: 'POST' }); selectedAssignment.value = null }, '提交已撤回') }
async function changeCampaignClasses(ids) {
  campaignForm.class_ids = ids
  Object.keys(campaignAssignmentIds).forEach(id => { if (!ids.includes(id)) delete campaignAssignmentIds[id] })
  Object.keys(campaignAssignmentsByClass).forEach(id => { if (!ids.includes(id)) delete campaignAssignmentsByClass[id] })
  if (!ids.length) return
  campaignOptionsLoading.value = true
  try {
    await Promise.all(ids.map(async id => {
      const [assignmentData, campaignData] = await Promise.all([api(`/assignments?class_id=${id}`), api(`/review-campaigns?class_id=${id}`)])
      const used = new Set(campaignData.items.map(item => item.assignment_id))
      campaignAssignmentsByClass[id] = assignmentData.items.filter(item => item.submitter_type === 'INDIVIDUAL' && !used.has(item.id))
      if (!campaignAssignmentsByClass[id].some(item => item.id === campaignAssignmentIds[id])) campaignAssignmentIds[id] = ''
    }))
  } catch (e) { message.error(e.message) }
  finally { campaignOptionsLoading.value = false }
}
async function openCampaignCreate() {
  Object.assign(campaignForm, { id: '', version: 1, has_reviews: false, class_ids: defaultClassSelection(), publish_at: '', due_at: '', comment_min_length: 20, require_all: false, allow_update: true })
  rubric.value = [{ label: '', weight: 100 }]
  Object.keys(campaignAssignmentIds).forEach(id => delete campaignAssignmentIds[id])
  Object.keys(campaignAssignmentsByClass).forEach(id => delete campaignAssignmentsByClass[id])
  modals.campaign = true; await changeCampaignClasses(campaignForm.class_ids)
}
function openCampaignEdit(item) {
  Object.assign(campaignForm, { id: item.id, version: item.version, has_reviews: item.completed > 0, class_ids: [classId.value], publish_at: localDateTime(item.publish_at), due_at: localDateTime(item.due_at), comment_min_length: item.comment_min_length, require_all: item.require_all, allow_update: item.allow_update })
  rubric.value = item.rubric.map(dim => ({ ...dim })); modals.campaign = true
}
async function createCampaign() {
  if (!campaignForm.id && !campaignForm.class_ids.length) return message.warning('请至少选择一个教学班')
  if (!campaignForm.id && campaignForm.class_ids.some(id => !campaignAssignmentIds[id])) return message.warning('请为每个教学班选择个人作业')
  if (!campaignForm.due_at) return message.warning('请选择截止时间')
  if (rubric.value.some(item => !item.label.trim())) return message.warning('请填写评分维度名称')
  if (rubric.value.reduce((sum, item) => sum + (Number(item.weight) || 0), 0) !== 100) return message.warning('评分维度权重合计须为 100%')
  const payload = { publish_at: campaignForm.publish_at ? iso(campaignForm.publish_at) : null, due_at: iso(campaignForm.due_at), comment_min_length: campaignForm.comment_min_length, require_all: campaignForm.require_all, allow_update: campaignForm.allow_update, rubric: rubric.value.map((item, index) => ({ ...item, key: item.key || `dimension_${index + 1}` })) }
  if (campaignForm.id) {
    await action(async () => { await api(`/review-campaigns/${campaignForm.id}`, { method: 'PATCH', body: JSON.stringify({ ...payload, version: campaignForm.version }) }); modals.campaign = false }, '互评活动已更新')
    return
  }
  const targets = campaignForm.class_ids.map(id => ({ class_id: id, assignment_id: campaignAssignmentIds[id] }))
  const count = targets.length
  await action(async () => {
    await api('/review-campaigns/bulk', {
      method: 'POST',
      body: JSON.stringify({ targets, ...payload })
    })
    modals.campaign = false
  }, `已为 ${count} 个教学班开启互评`)
}
async function openCampaign(item) {
  selectedCampaign.value = item
  if (role.value === 'STUDENT') candidates.value = (await api(`/review-campaigns/${item.id}/candidates`)).items
  else {
    const [stats, reviews] = await Promise.all([api(`/review-campaigns/${item.id}/stats`), api(`/review-campaigns/${item.id}/reviews`)])
    campaignStats.value = stats; campaignReviews.value = reviews.items
  }
}
function startReview(person) { reviewForm.reviewee_id = person.user_id; reviewForm.comment = person.review?.comment || ''; reviewForm.scores = person.review?.scores || Object.fromEntries(selectedCampaign.value.rubric.map(x => [x.key, 0])); modals.review = true }
async function submitReview() { await action(async () => { await api(`/review-campaigns/${selectedCampaign.value.id}/reviews`, { method: 'POST', body: JSON.stringify(reviewForm) }); modals.review = false; await openCampaign(selectedCampaign.value) }, '评价已提交') }
function openInvalidate(item) { selectedReview.value = item; invalidReason.value = ''; modals.invalidate = true }
async function invalidateReview() { await action(async () => { await api(`/peer-reviews/${selectedReview.value.id}/invalidate`, { method: 'POST', body: JSON.stringify({ reason: invalidReason.value }) }); modals.invalidate = false; await openCampaign(selectedCampaign.value) }, '评价已作废') }
async function readAll() { await action(() => api('/notifications/read', { method: 'POST' }), '已全部标为已读'); noticesOpen.value = false }
async function changePassword() { await action(async () => { await api('/auth/password', { method: 'POST', body: JSON.stringify(passwordForm) }); modals.password = false; await session.logout(); await router.replace('/login') }, '密码已修改，请重新登录') }
function editGrade(item) { Object.assign(gradeForm, { assignment_id: item.assignment_id, subject_user_id: item.subject_type === 'USER' ? item.subject_id : '', subject_team_id: item.subject_type === 'TEAM' ? item.subject_id : '', score: item.score, comment: item.comment, publish: item.status === 'PUBLISHED', reason: '' }); modals.grade = true }
async function openGradeRevisions(item) { try { selectedGrade.value = item; gradeRevisions.value = (await api(`/grades/${item.id}/revisions`)).items } catch (e) { message.error(e.message) } }
async function persistGrade() { await action(async () => { const payload = { ...gradeForm, subject_user_id: gradeForm.subject_user_id || null, subject_team_id: gradeForm.subject_team_id || null }; await api('/grades', { method: 'POST', body: JSON.stringify(payload) }); modals.grade = false }, gradeForm.publish ? '成绩已发布' : '评分草稿已保存') }
async function saveGrade() { if (!gradeForm.publish) return persistGrade(); const preview = gradePublishPreview.value; Modal.confirm({ title: '确认发布成绩？', content: preview ? `${preview.assignment}：已评分 ${preview.scored}，未评分 ${preview.pending}，当前成绩范围 ${preview.range}。发布后学生即可查看该成绩和评语。` : '发布后学生即可查看该成绩和评语。', okText: '确认发布', cancelText: '取消', onOk: persistGrade }) }
async function logout() { await session.logout(); await router.replace('/login') }
function downloadExport(kind, format = 'xlsx') { window.location.href = `/api/v1/exports/${kind}.${format}?class_id=${classId.value}` }

async function pollGate() {
  if (!session.teamGate) return
  const before = session.teamGate
  await session.refreshContext()
  if (before && !session.teamGate) { message.success('已加入小组'); clearInterval(gateTimer); await router.replace('/overview') }
}

watch(() => route.params.view, loadView)
watch(() => session.teamGate, required => { clearInterval(gateTimer); gateTimer = required ? setInterval(pollGate, 10000) : undefined })
onMounted(async () => { await loadView(); if (session.teamGate) gateTimer = setInterval(pollGate, 10000); window.addEventListener('focus', pollGate) })
onBeforeUnmount(() => { clearInterval(gateTimer); window.removeEventListener('focus', pollGate) })
</script>

<template>
  <a-layout class="app-shell">
    <a-layout-header class="app-header">
      <div class="header-toolbar">
        <div class="header-left"><div class="header-brand"><div class="brand-mark"><CodeOutlined /></div><strong>软件工程</strong></div><a-select v-if="session.classes.length" class="class-switch" :value="classId" :options="session.classes.map(x => ({value:x.id,label:`${x.semester} · ${x.name}`}))" @change="changeClass" /></div>
        <div class="header-right"><a-badge :count="notifications.filter(x=>!x.read).length" size="small"><a-button type="text" shape="circle" @click="noticesOpen=true"><BellOutlined /></a-button></a-badge><a-dropdown><div class="user-chip"><a-avatar :style="{background:role==='TEACHER'?'#7352bd':'#1769aa'}">{{ session.user.name.slice(0,1) }}</a-avatar><div class="user-meta"><strong>{{ session.user.name }}</strong><span>{{ role==='TEACHER'?'教师':'学生' }}</span></div></div><template #overlay><a-menu><a-menu-item @click="modals.password=true"><UserOutlined /> 修改密码</a-menu-item><a-menu-item @click="logout"><LogoutOutlined /> 退出登录</a-menu-item></a-menu></template></a-dropdown></div>
      </div>
      <nav class="top-nav" aria-label="主导航"><button v-for="item in menu" :key="item[0]" :class="{active:view===item[0]}" @click="router.push('/'+item[0])"><component :is="item[1]" />{{ item[2] }}</button></nav>
    </a-layout-header>
    <a-layout-content class="app-content"><div class="content-wrap"><a-spin :spinning="loading">
      <template v-if="view==='overview'">
        <div class="page-title"><div><div class="eyebrow">{{ role==='TEACHER'?'教师工作台':'学生学习台' }}</div><h1>{{ session.context?.current_class?.name || '还没有教学班' }}</h1><p>{{ classId ? (role==='TEACHER'?'掌握教学班、小组和课程任务的整体进展。':'查看我的小组、待完成作业和课程反馈。') : (role==='TEACHER'?'创建教学班后即可导入学生并开展课程。':'使用教师提供的邀请码加入教学班。') }}</p></div><a-button v-if="role==='TEACHER'&&!classId" type="primary" @click="openClassCreate"><PlusOutlined /> 创建教学班</a-button></div>
        <a-empty v-if="!classId" description="暂无教学班"><a-button v-if="role==='STUDENT'" type="primary" @click="modals.joinClass=true">通过邀请码加入教学班</a-button></a-empty>
        <div v-else-if="role==='TEACHER'" class="stat-grid"><div class="stat-card"><UserOutlined class="stat-icon blue"/><div class="stat-body"><span>教学班人数</span><strong>{{ dashboard?.summary.member_count||0 }}<small>人</small></strong></div></div><div class="stat-card"><TeamOutlined class="stat-icon purple"/><div class="stat-body"><span>当前小组</span><strong>{{ dashboard?.summary.team_count||0 }}<small>组</small></strong></div></div><div class="stat-card"><FileTextOutlined class="stat-icon green"/><div class="stat-body"><span>进行中作业</span><strong>{{ dashboard?.summary.active_assignments||0 }}<small>项</small></strong></div></div><div class="stat-card"><CheckCircleOutlined class="stat-icon green"/><div class="stat-body"><span>提交进度</span><strong>{{ dashboard?.summary.submission_rate||0 }}<small>%</small></strong></div></div><div class="stat-card"><FormOutlined class="stat-icon blue"/><div class="stat-body"><span>互评参与率</span><strong>{{ dashboard?.summary.peer_review_rate||0 }}<small>%</small></strong></div></div></div>
        <div v-else class="student-overview"><a-card class="student-focus" :bordered="false"><TeamOutlined class="student-focus-icon purple"/><div><span>当前小组与选题</span><strong>{{currentTeam?.name||'尚未加入小组'}}</strong><p>{{currentTeam?.topic?.name||'暂未提交选题'}}</p></div></a-card><div class="stat-grid"><div class="stat-card"><FileTextOutlined class="stat-icon blue"/><div class="stat-body"><span>待提交作业</span><strong>{{studentPendingAssignments.length}}<small>项</small></strong></div></div><div class="stat-card"><CheckCircleOutlined class="stat-icon orange"/><div class="stat-body"><span>72 小时内截止</span><strong>{{studentUpcomingAssignments.length}}<small>项</small></strong></div></div><div class="stat-card"><FormOutlined class="stat-icon purple"/><div class="stat-body"><span>待完成互评</span><strong>{{studentPendingReviews}}<small>份</small></strong></div></div><div class="stat-card"><TrophyOutlined class="stat-icon green"/><div class="stat-body"><span>最新成绩</span><strong>{{studentLatestGrade?studentLatestGrade.score:'-' }}<small v-if="studentLatestGrade">分</small></strong></div></div></div><a-card class="panel-card student-todo-card" :bordered="false"><div class="card-toolbar"><strong>近期待办</strong><a-button type="link" @click="router.push('/assignments')">查看作业</a-button></div><a-empty v-if="!studentPendingAssignments.length&&!studentPendingReviews" description="当前没有待完成事项"/><div v-for="item in studentPendingAssignments.slice(0,3)" :key="item.id" class="student-todo-row"><FileTextOutlined/><div><strong>{{item.title}}</strong><span>截止 {{formatTime(item.due_at)}}</span></div><a-tag v-if="item.starts_at&&new Date(item.starts_at)>new Date()">未开始</a-tag><a-tag v-else color="orange">待提交</a-tag></div><div v-if="studentPendingReviews" class="student-todo-row"><FormOutlined/><div><strong>组内作品互评</strong><span>还有 {{studentPendingReviews}} 份评价待完成</span></div><a-tag color="blue">待互评</a-tag></div></a-card></div>
      </template>

       <template v-else-if="view==='classes'&&role==='TEACHER'">
        <div class="page-title"><div><div class="eyebrow">课程管理</div><h1>教学班</h1><p>管理教学班资料、状态和正式成员名单。</p></div><a-button type="primary" @click="openClassCreate"><PlusOutlined /> 创建教学班</a-button></div>
        <a-card class="panel-card class-list-panel" :bordered="false"><a-empty v-if="!session.classes.length" description="暂无教学班"/><a-table v-else :data-source="session.classes" row-key="id" :pagination="false" :scroll="{x:760}"><a-table-column title="学期" data-index="semester"/><a-table-column title="班级名称" data-index="name"/><a-table-column title="成员" data-index="member_count" :width="90"/><a-table-column title="作业" data-index="assignment_count" :width="90"/><a-table-column title="状态" :width="100"><template #default="{record}"><a-tag :color="record.status==='ACTIVE'?'green':'default'">{{record.status==='ACTIVE'?'进行中':'已归档'}}</a-tag></template></a-table-column><a-table-column title="操作" :width="270" fixed="right"><template #default="{record}"><a-space><a-tooltip title="管理教学班"><a-button type="text" shape="circle" @click="manageClass(record)"><EyeOutlined/></a-button></a-tooltip><a-tooltip title="编辑教学班"><a-button type="text" shape="circle" :disabled="record.status!=='ACTIVE'" @click="openClassEdit(record)"><EditOutlined/></a-button></a-tooltip><a-tooltip :title="record.status==='ACTIVE'?'归档教学班':'恢复教学班'"><a-button type="text" shape="circle" @click="toggleClassStatus(record)"><InboxOutlined v-if="record.status==='ACTIVE'"/><RedoOutlined v-else/></a-button></a-tooltip><a-tooltip :title="record.deletable?'删除空班':'已有历史数据，只能归档'"><span><a-button danger type="text" shape="circle" :disabled="!record.deletable" @click="deleteClass(record)"><DeleteOutlined/></a-button></span></a-tooltip></a-space></template></a-table-column></a-table></a-card>
        <a-card class="panel-card" :bordered="false"><a-empty v-if="!classId" description="请先创建教学班"/><template v-else><div class="card-toolbar"><div><strong>{{session.context?.current_class?.name}}成员</strong><span class="class-member-caption">{{session.context?.current_class?.semester}}</span></div><a-space><a-input-search v-model:value="memberQuery" allow-clear placeholder="搜索学号、姓名或小组" style="width:280px;max-width:100%"/><a-button @click="modals.import=true" :disabled="session.context?.current_class?.status!=='ACTIVE'"><UploadOutlined /> 导入名单</a-button><a-button type="primary" :disabled="session.context?.current_class?.status!=='ACTIVE'" @click="openMemberCreate"><PlusOutlined /> 添加成员</a-button></a-space></div><a-table :data-source="filteredMembers" row-key="id" :pagination="{pageSize:10}" :scroll="{x:700}"><a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="name"/><a-table-column title="小组"><template #default="{record}">{{ record.team||'未入组' }}</template></a-table-column><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="操作" :width="172"><template #default="{record}"><a-space><a-tooltip title="查看"><a-button type="text" shape="circle" @click="openMemberDetail(record)"><EyeOutlined/></a-button></a-tooltip><a-tooltip title="编辑"><a-button type="text" shape="circle" :disabled="session.context?.current_class?.status!=='ACTIVE'" @click="openMemberEdit(record)"><EditOutlined/></a-button></a-tooltip><a-tooltip title="重置密码"><a-button type="text" shape="circle" :disabled="session.context?.current_class?.status!=='ACTIVE'" @click="resetMemberPassword(record)"><KeyOutlined/></a-button></a-tooltip><a-tooltip title="移出教学班"><a-button danger type="text" shape="circle" :disabled="session.context?.current_class?.status!=='ACTIVE'" @click="removeClassMember(record)"><DeleteOutlined/></a-button></a-tooltip></a-space></template></a-table-column></a-table></template></a-card>
         <a-card v-if="classId" class="panel-card" :bordered="false">
          <div class="card-toolbar"><strong>邀请码加入申请</strong><a-typography-text copyable>{{session.context?.current_class?.invite_code}}</a-typography-text></div>
          <a-empty v-if="!classJoinRequests.length" description="暂无申请"/>
          <a-table v-else :data-source="classJoinRequests" row-key="id" size="small"><a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="name"/><a-table-column title="申请时间"><template #default="{record}">{{formatTime(record.created_at)}}</template></a-table-column><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="操作"><template #default="{record}"><a-space v-if="record.status==='PENDING'"><a-tooltip title="拒绝申请"><a-button danger type="text" shape="circle" @click="decideClassJoin(record,'REJECTED')"><CloseOutlined/></a-button></a-tooltip><a-tooltip title="同意申请"><a-button type="text" shape="circle" @click="decideClassJoin(record,'APPROVED')"><CheckCircleOutlined/></a-button></a-tooltip></a-space></template></a-table-column></a-table>
        </a-card>
      </template>

      <template v-else-if="view==='teams'">
        <div class="page-title"><div><div class="eyebrow">{{ role==='TEACHER'?'教学组织':session.teamGate?'开始课程前':'协作空间' }}</div><h1>{{ role==='TEACHER'?'小组与选题':session.teamGate?'加入小组':'我的小组' }}</h1><p>{{ role==='TEACHER'?'审核各组选题，查看成员配置并处理异常。':session.teamGate?'创建小组或申请加入已有小组。入组后将自动进入教学班首页。':'管理本组成员、邀请和选题信息。' }}</p></div><a-button v-if="role==='STUDENT'&&session.teamGate" type="primary" @click="modals.team=true"><PlusOutlined /> 创建小组</a-button><a-button v-if="role==='TEACHER'" @click="downloadExport('teams')"><DownloadOutlined /> 导出小组名单</a-button></div>
        <a-alert v-if="session.teamGate" type="info" show-icon message="加入小组后解锁课程功能" class="soft-alert"/>
        <div v-if="role==='STUDENT'" class="team-grid"><a-card v-for="item in teams" :key="item.id" class="team-card" :bordered="false"><div class="team-card-top"><a-avatar shape="square">{{item.name.slice(0,1)}}</a-avatar><a-tag :color="item.open_recruitment?'blue':'default'">{{item.open_recruitment?'招募中':'未开放'}}</a-tag></div><h3>{{item.name}}</h3><p>{{item.topic?.name||(session.context?.current_class?.topic_public?'暂未提交选题':'选题未公开')}}</p><div class="team-card-meta"><span>{{item.member_count}} / {{item.max_members}} 人</span><span>组长：{{item.leader_name}}</span></div><a-divider/><a-space wrap><a-button v-if="session.teamGate&&item.open_recruitment" type="primary" ghost @click="applyTeam(item)">申请加入</a-button><a-button v-if="item.is_leader" type="primary" @click="openTeam(item)">{{item.topic?'修改选题':'提交选题'}}</a-button><a-button @click="openTeam(item)">查看详情</a-button></a-space></a-card><a-empty v-if="!teams.length" description="暂无小组，可创建第一个小组"/></div>
        <a-card v-else class="panel-card" :bordered="false"><a-table :data-source="teams" row-key="id"><a-table-column title="小组" data-index="name"/><a-table-column title="组长" data-index="leader_name"/><a-table-column title="人数"><template #default="{record}">{{record.member_count}} / {{record.max_members}}</template></a-table-column><a-table-column title="选题"><template #default="{record}">{{record.topic?.name||'-'}}</template></a-table-column><a-table-column title="操作"><template #default="{record}"><a-space><a-tooltip title="查看小组"><a-button type="text" shape="circle" @click="openTeam(record)"><EyeOutlined/></a-button></a-tooltip><a-tooltip v-if="record.topic?.status==='PENDING'" title="通过选题"><a-button type="text" shape="circle" @click="decideTopic(record,'APPROVED')"><CheckCircleOutlined/></a-button></a-tooltip><a-tooltip v-if="record.topic?.status==='PENDING'" title="退回选题"><a-button danger type="text" shape="circle" @click="decideTopic(record,'REJECTED')"><CloseOutlined/></a-button></a-tooltip></a-space></template></a-table-column></a-table></a-card>
        <a-card v-if="requests.length" class="panel-card request-card" title="入组申请与邀请" :bordered="false"><div v-for="item in requests" :key="item.id" class="request-row"><div><strong>{{item.is_incoming?item.applicant_name:item.team_name}}</strong><span>{{item.kind==='INVITATION'?'小组邀请':item.is_incoming?'申请加入你的小组':`申请状态：${statusLabel(item.status)}`}}</span></div><a-space v-if="item.is_incoming&&item.kind==='APPLICATION'&&item.status==='PENDING'"><a-button @click="decideRequest(item,'REJECTED')">拒绝</a-button><a-button type="primary" @click="decideRequest(item,'APPROVED')">同意</a-button></a-space><a-space v-else-if="item.kind==='INVITATION'&&!item.is_incoming&&item.status==='PENDING'"><a-button @click="respondInvitation(item,'REJECTED')">拒绝</a-button><a-button type="primary" @click="respondInvitation(item,'APPROVED')">接受</a-button></a-space><a-button v-else-if="!item.is_incoming&&item.status==='PENDING'" @click="cancelRequest(item)">取消申请</a-button><a-tag v-else>{{statusLabel(item.status)}}</a-tag></div></a-card>
      </template>

      <template v-else-if="view==='assignments'">
        <div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'教学任务':'学习任务'}}</div><h1>{{role==='TEACHER'?'作业管理':'我的作业'}}</h1><p>{{role==='TEACHER'?'发布作业、维护附件并查看全班提交情况。':'查看作业要求，管理草稿并完成正式提交。'}}</p></div><a-button v-if="role==='TEACHER'" type="primary" :disabled="!activeClasses.length" @click="openAssignmentCreate"><PlusOutlined /> 新建作业</a-button></div>
        <a-empty v-if="!assignments.length" description="暂无作业"/><a-card v-for="item in assignments" :key="item.id" class="assignment-row" :bordered="false" @click="openAssignment(item)"><div class="assignment-icon blue"><FileTextOutlined/></div><div class="assignment-main"><h3>{{item.title}}</h3><p>{{item.description}}</p><span>截止 {{formatTime(item.due_at)}}</span></div><div class="assignment-end"><a-tag>{{item.submitter_type==='INDIVIDUAL'?'个人作业':'小组作业'}}</a-tag><a-tag :color="item.status==='PUBLISHED'?'green':'default'">{{statusLabel(item.status)}}</a-tag></div></a-card>
      </template>

       <template v-else-if="view==='reviews'">
        <div class="page-title"><div><div class="eyebrow">组内作品互评</div><h1>{{role==='TEACHER'?'互评管理':'作品互评'}}</h1><p>{{role==='TEACHER'?'为个人作业开启组内作品评价。':'选择同组成员已正式提交的作品进行评分。'}}</p></div><a-button v-if="role==='TEACHER'" type="primary" :disabled="!activeClasses.length" @click="openCampaignCreate"><PlusOutlined /> 开启互评</a-button></div>
        <a-empty v-if="!campaigns.length" description="暂无互评活动"/><a-card v-for="item in campaigns" :key="item.id" class="review-card" :bordered="false"><div class="review-card-head"><FormOutlined class="review-symbol purple"/><div><h3>{{item.assignment_title}}</h3><span>公开 {{formatTime(item.publish_at)}} · 截止 {{formatTime(item.due_at)}}</span></div><a-tag color="blue">{{statusLabel(item.status)}}</a-tag><a-button v-if="role==='TEACHER'" @click="openCampaignEdit(item)"><EditOutlined/> 编辑</a-button><a-button :type="role==='STUDENT'?'primary':'default'" @click="openCampaign(item)">{{role==='STUDENT'?'选择作品':'查看统计'}}</a-button></div></a-card>
        <a-card v-if="role==='STUDENT'" class="panel-card" title="收到的评价" :bordered="false"><a-empty v-if="!receivedReviews.length" description="暂无收到的评价"/><div v-for="item in receivedReviews" :key="item.id" class="review-received"><strong>{{item.assignment_title}} · {{item.total_score}} 分</strong><span>{{item.reviewer_name}}</span><p>{{item.comment}}</p></div></a-card><a-card v-if="role==='STUDENT'" class="panel-card" title="我发出的评价" :bordered="false"><a-empty v-if="!sentReviews.length" description="暂无发出的评价"/><a-table v-else :data-source="sentReviews" row-key="id" size="small"><a-table-column title="作业" data-index="assignment_title"/><a-table-column title="评价对象" data-index="reviewee_name"/><a-table-column title="分数" data-index="total_score"/><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="评语" data-index="comment"/></a-table></a-card>
      </template>

      <template v-else-if="view==='grades'"><div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'教学评价':'学习成果'}}</div><h1>{{role==='TEACHER'?'成绩与导出':'成绩与反馈'}}</h1><p>{{role==='TEACHER'?'录入、发布和导出教学班成绩。':'查看教师已发布的成绩与评语。'}}</p></div><a-space v-if="role==='TEACHER'"><a-button @click="downloadExport('grades')"><DownloadOutlined/> 导出 XLSX</a-button><a-button @click="downloadExport('grades','csv')"><DownloadOutlined/> 导出 CSV</a-button><a-button type="primary" @click="modals.grade=true"><PlusOutlined/> 录入成绩</a-button></a-space></div><a-empty v-if="!grades.length" :description="role==='TEACHER'?'暂无成绩记录':'暂无已发布成绩'"/><a-table v-else :data-source="grades" row-key="id"><a-table-column title="作业" data-index="assignment_title"/><a-table-column v-if="role==='TEACHER'" title="评分对象" data-index="subject_name"/><a-table-column title="成绩" data-index="score"/><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="评语" data-index="comment"/><a-table-column v-if="role==='TEACHER'" title="操作"><template #default="{record}"><a-tooltip title="编辑成绩"><a-button type="text" shape="circle" @click="editGrade(record)"><EditOutlined/></a-button></a-tooltip><a-tooltip title="查看修订记录"><a-button type="text" shape="circle" @click="openGradeRevisions(record)"><FileTextOutlined/></a-button></a-tooltip></template></a-table-column></a-table></template>
      <template v-else-if="view==='system'&&role==='TEACHER'"><div class="page-title"><div><div class="eyebrow">运行管理</div><h1>系统与审计</h1><p>关键业务操作不可修改。</p></div></div><a-empty v-if="!audits.length" description="暂无审计记录"/><a-table v-else :data-source="audits" row-key="id"><a-table-column title="时间"><template #default="{record}">{{formatTime(record.created_at)}}</template></a-table-column><a-table-column title="操作者" data-index="actor"/><a-table-column title="操作"><template #default="{record}">{{actionLabel(record.action)}}</template></a-table-column><a-table-column title="对象"><template #default="{record}">{{objectLabel(record.object_type)}}</template></a-table-column></a-table></template>
    </a-spin></div></a-layout-content>

    <a-modal v-model:open="noticesOpen" title="站内通知" :footer="null" width="520px" centered><div class="notification-toolbar"><span>{{notifications.filter(x=>!x.read).length ? `${notifications.filter(x=>!x.read).length} 条未读消息` : '消息已全部阅读'}}</span><a-button v-if="notifications.some(x=>!x.read)" type="link" @click="readAll">全部标为已读</a-button></div><a-empty v-if="!notifications.length" description="暂无通知"/><div v-else class="notification-list"><div v-for="item in notifications" :key="item.id" class="notification-item" :class="{unread:!item.read}"><span class="notification-dot"/><div><strong>{{item.title}}</strong><span>{{formatTime(item.created_at)}}</span></div></div></div></a-modal>

    <a-modal v-model:open="modals.class" :title="classForm.id?'编辑教学班':'创建教学班'" ok-text="保存" @ok="saveClass"><a-form layout="vertical"><a-form-item label="课程"><a-input value="软件工程" disabled/></a-form-item><a-form-item label="学期" required><a-input v-model:value="classForm.semester" placeholder="例如：2026 秋季"/></a-form-item><a-form-item label="班级名称" required><a-input v-model:value="classForm.name"/></a-form-item><a-form-item label="组队截止时间"><a-input v-model:value="classForm.team_deadline" type="datetime-local"/></a-form-item><a-form-item label="小组人数上限"><a-input-number v-model:value="classForm.max_team_members" :min="2" :max="20"/></a-form-item><a-form-item label="选题可见性"><a-switch v-model:checked="classForm.topic_public" checked-children="公开" un-checked-children="仅本组"/></a-form-item><a-form-item label="邀请码加入"><a-switch v-model:checked="classForm.invite_requires_approval" checked-children="需审核" un-checked-children="自动加入"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.joinClass" title="通过邀请码加入教学班" ok-text="提交申请" @ok="joinClass"><a-form layout="vertical"><a-form-item label="邀请码" required><a-input v-model:value="joinClassForm.invite_code" maxlength="12" placeholder="请输入教师提供的邀请码"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.import" title="导入学生名单" :footer="null" @cancel="closeImport"><a-steps :current="importState.step" size="small" :items="[{title:'上传名单'},{title:'预览校验'},{title:'确认导入'}]"/><a-upload-dragger v-if="!importState.result" :before-upload="chooseRoster" :show-upload-list="true" :max-count="1" accept=".csv,.xlsx"><p class="ant-upload-drag-icon"><UploadOutlined/></p><p>选择 XLSX 或 CSV 名单</p><p class="ant-upload-hint">必填列：学号、姓名</p></a-upload-dragger><a-table v-if="importState.preview" :data-source="importState.preview.rows" size="small" row-key="row" :pagination="{pageSize:5}"><a-table-column title="行" data-index="row"/><a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="name"/><a-table-column title="结果" data-index="reason"/></a-table><a-result v-if="importState.result" status="success" title="名单导入完成" :sub-title="`新建 ${importState.result.created} 个账号，加入 ${importState.result.joined} 名学生，跳过 ${importState.result.skipped} 行`"/><div class="modal-actions"><a-button @click="closeImport">{{importState.result?'关闭':'取消'}}</a-button><a-button v-if="!importState.preview" type="primary" :loading="importState.loading" @click="previewRoster">校验名单</a-button><a-button v-else-if="!importState.result" type="primary" :loading="importState.loading" @click="confirmRoster">确认导入</a-button><a-button v-else :href="`/api/v1/classes/${classId}/members/import/${importState.preview.batch_id}/result.csv`"><DownloadOutlined/> 下载结果</a-button></div></a-modal>
    <a-modal v-model:open="modals.member" :title="memberForm.id?'编辑成员':'添加成员'" :confirm-loading="memberSaving" ok-text="保存" @ok="saveMember"><a-form layout="vertical"><a-form-item label="学号" required><a-input v-model:value="memberForm.student_no" :disabled="Boolean(memberForm.id)" maxlength="32"/></a-form-item><a-form-item label="姓名" required><a-input v-model:value="memberForm.name" maxlength="80"/></a-form-item></a-form></a-modal>
    <a-modal :open="Boolean(memberDetail)" title="成员信息" :footer="null" @cancel="memberDetail=null"><a-descriptions v-if="memberDetail" bordered :column="1"><a-descriptions-item label="学号">{{memberDetail.student_no}}</a-descriptions-item><a-descriptions-item label="姓名">{{memberDetail.name}}</a-descriptions-item><a-descriptions-item label="小组">{{memberDetail.team||'未入组'}}</a-descriptions-item><a-descriptions-item label="加入时间">{{formatTime(memberDetail.joined_at)}}</a-descriptions-item></a-descriptions></a-modal>
    <a-modal v-model:open="modals.team" title="创建小组" @ok="createTeam"><a-form layout="vertical"><a-form-item label="小组名称" required><a-input v-model:value="teamForm.name"/></a-form-item><a-checkbox v-model:checked="teamForm.open_recruitment">允许其他成员申请加入</a-checkbox></a-form></a-modal>
    <a-modal v-model:open="selectedTeam" :title="selectedTeam?.name" :footer="null"><template v-if="selectedTeam"><p>组长：{{selectedTeam.leader_name}} · {{selectedTeam.member_count}} / {{selectedTeam.max_members}} 人</p><a-list :data-source="selectedTeam.members||[]"><template #renderItem="{item}"><a-list-item>{{item.name}}（{{item.student_no}}）<a-space><a-tag>{{roleLabel(item.role)}}</a-tag><a-button v-if="selectedTeam.is_leader&&item.role!=='LEADER'" type="link" @click="transferLeader(item.id)">移交组长</a-button><a-button v-if="role==='TEACHER'" danger type="link" @click="removeTeamMember(item)">移出</a-button></a-space></a-list-item></template></a-list><template v-if="selectedTeam.is_leader"><a-divider/><a-space-compact block><a-select v-model:value="inviteTarget" placeholder="选择未入组学生" style="width:100%" :options="members.filter(x=>!x.team).map(x=>({value:x.id,label:`${x.name}（${x.student_no}）`}))"/><a-button type="primary" :disabled="!inviteTarget" @click="inviteMember">邀请</a-button></a-space-compact><a-divider/><a-form layout="vertical"><a-form-item label="选题名称"><a-input v-model:value="topicForm.name"/></a-form-item><a-form-item label="选题说明"><a-textarea v-model:value="topicForm.description" :rows="3"/></a-form-item><a-space><a-button type="primary" @click="saveTopic">提交选题审核</a-button><a-button danger @click="disbandTeam">解散小组</a-button></a-space></a-form></template><a-button v-else-if="role==='STUDENT'&&selectedTeam.id===session.context?.team_membership?.team_id" danger @click="leaveTeam">退出小组</a-button></template></a-modal>
    <a-modal v-model:open="modals.assignment" :title="assignmentForm.id ? '编辑作业' : '新建作业'" @ok="createAssignment"><a-form layout="vertical"><a-form-item v-if="!assignmentForm.id" label="教学班" required><a-select v-model:value="assignmentForm.class_ids" mode="multiple" placeholder="选择一个或多个教学班" :options="classOptions"/></a-form-item><a-form-item label="标题" required><a-input v-model:value="assignmentForm.title"/></a-form-item><a-form-item label="提交类型" :help="assignmentForm.has_submissions ? '已有提交，不能修改提交类型' : ''"><a-segmented :disabled="assignmentForm.has_submissions" v-model:value="assignmentForm.submitter_type" :options="[{label:'个人作业',value:'INDIVIDUAL'},{label:'小组作业',value:'TEAM'}]"/></a-form-item><a-form-item label="开始时间"><a-input v-model:value="assignmentForm.starts_at" type="datetime-local"/></a-form-item><a-form-item label="截止时间" required><a-input v-model:value="assignmentForm.due_at" type="datetime-local"/></a-form-item><a-form-item label="说明" required><a-textarea v-model:value="assignmentForm.description" :rows="4"/></a-form-item><a-form-item v-if="!assignmentForm.id" label="作业附件"><a-upload :before-upload="queueAssignmentAttachment" :show-upload-list="false" multiple accept=".md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.pptx,.xlsx,.zip,.rar,.7z"><a-button><UploadOutlined/> 选择附件</a-button></a-upload><div v-for="(file,index) in pendingAssignmentFiles" :key="file.uid||`${file.name}-${index}`" class="uploaded-file"><span>{{file.name}}</span><a-button danger type="link" @click="removePendingAssignmentAttachment(index)">移除</a-button></div></a-form-item><a-space direction="vertical"><a-checkbox v-model:checked="assignmentForm.allow_late">允许迟交并标记</a-checkbox><a-checkbox v-if="!assignmentForm.id" v-model:checked="assignmentForm.publish">立即发布</a-checkbox></a-space></a-form></a-modal>
    <a-modal v-model:open="selectedAssignment" :title="selectedAssignment?.title" :footer="null" width="760px">
      <template v-if="selectedAssignment">
        <p>{{selectedAssignment.description}}</p>
        <p>开始：{{formatTime(selectedAssignment.starts_at)}}　截止：{{formatTime(selectedAssignment.due_at)}}</p>
        <a-divider orientation="left">作业附件</a-divider>
        <a-empty v-if="!assignmentAttachments.length" description="暂无附件"/>
        <div v-for="file in assignmentAttachments" :key="file.id" class="uploaded-file">
          <a :href="`/api/v1/files/${file.id}/preview`" target="_blank">{{file.name}}</a><span>{{file.owner_name}}</span>
          <a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip>
          <a-tag v-if="file.preview_status==='PENDING'" color="processing">预览生成中</a-tag>
          <a-tooltip v-else-if="file.preview_status==='FAILED'" :title="file.preview_error||'转换服务不可用，请下载原文件查看'"><a-tag color="error">预览失败</a-tag></a-tooltip>
          <a-tag v-else-if="file.preview_status==='NOT_AVAILABLE'">仅下载</a-tag>
          <a-button v-if="role==='TEACHER'" danger type="link" @click="deleteDraft(file)">删除</a-button>
        </div>
        <template v-if="role==='STUDENT'">
          <a-divider orientation="left">提交草稿</a-divider>
          <a-upload :custom-request="uploadFile" multiple><a-button><UploadOutlined/> 上传文件</a-button></a-upload>
          <a-checkbox-group v-model:value="selectedFileIds" class="draft-file-list"><div v-for="file in draftFiles" :key="file.id" class="uploaded-file"><a-checkbox :value="file.id" :disabled="file.submitted"/><a :href="`/api/v1/files/${file.id}/preview`" target="_blank">{{file.name}}</a><span>{{file.owner_name}}</span><a-tag>{{file.submitted?'已提交':'草稿'}}</a-tag><a-tooltip v-if="file.preview_status==='FAILED'" :title="file.preview_error||'转换服务不可用，请下载原文件查看'"><a-tag color="error">预览失败</a-tag></a-tooltip><a-tag v-else-if="file.preview_status==='PENDING'" color="processing">预览生成中</a-tag><a-tag v-else-if="file.preview_status==='NOT_AVAILABLE'">仅下载</a-tag><a-button v-if="!file.submitted" danger type="link" @click="deleteDraft(file)">删除</a-button></div></a-checkbox-group>
          <a-space><a-button type="primary" :disabled="!selectedFileIds.length" @click="submitAssignment">正式提交</a-button><a-button v-if="selectedAssignment.submission?.status==='SUBMITTED'&&new Date(selectedAssignment.due_at)>new Date()" danger @click="retractAssignment">撤回</a-button></a-space>
          <a-divider/><a-timeline><a-timeline-item v-for="v in selectedAssignment.submission?.versions" :key="v.id">V{{v.version_no}} · {{formatTime(v.submitted_at)}} · {{v.files.map(x=>x.name).join('、')}} <a-tag v-if="v.is_late" color="red">迟交</a-tag></a-timeline-item></a-timeline>
        </template>
        <template v-else>
          <a-space><a-button @click="openAssignmentEdit"><EditOutlined/> 编辑作业</a-button><a-upload :custom-request="uploadFile"><a-button><UploadOutlined/> 上传作业附件</a-button></a-upload><a-button v-if="selectedAssignment.status==='DRAFT'" type="primary" @click="publishAssignment">发布作业</a-button><a-button :href="`/api/v1/assignments/${selectedAssignment.id}/download.zip`" target="_blank"><DownloadOutlined/> 批量下载</a-button></a-space>
          <a-space class="board-toolbar" wrap><a-input-search v-model:value="boardQuery" allow-clear placeholder="搜索成员或小组" style="width:220px"/><a-segmented v-model:value="boardFilter" :options="[{label:'全部',value:'ALL'},{label:'未提交',value:'NOT_SUBMITTED'},{label:'已提交',value:'SUBMITTED'},{label:'迟交',value:'LATE'}]"/></a-space>
          <a-table :data-source="filteredBoard" row-key="id" size="small" :pagination="false"><template #expandedRowRender="{record}"><a-empty v-if="!record.versions?.length" description="暂无提交版本"/><a-timeline v-else><a-timeline-item v-for="version in record.versions" :key="version.version_no"><div class="submission-version-head">V{{version.version_no}} · {{formatTime(version.submitted_at)}} <a-tag v-if="version.is_late" color="red">迟交</a-tag></div><div class="submission-files"><span v-if="!version.files.length">该版本没有文件</span><a-space v-else wrap><span v-for="file in version.files" :key="file.id" class="submission-file"><a :href="`/api/v1/files/${file.id}/preview`" target="_blank">{{file.name}}</a><a-tooltip title="下载原文件"><a-button type="text" size="small" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip></span></a-space></div></a-timeline-item></a-timeline></template><a-table-column title="提交对象" data-index="owner"/><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag><a-tag v-if="record.is_late" color="red">迟交</a-tag></template></a-table-column><a-table-column title="版本" data-index="version_no"/><a-table-column title="时间"><template #default="{record}">{{formatTime(record.submitted_at)}}</template></a-table-column><a-table-column title="最新提交" :width="110"><template #default="{record}"><a-button v-if="record.versions?.[0]?.files?.length" type="link" :href="`/api/v1/files/${record.versions[0].files[0].id}/preview`" target="_blank"><EyeOutlined/> 查看</a-button><span v-else>-</span></template></a-table-column></a-table>
        </template>
      </template>
    </a-modal>
    <a-modal v-model:open="modals.campaign" :title="campaignForm.id?'编辑组内作品互评':'开启组内作品互评'" @ok="createCampaign" width="680px"><a-form layout="vertical"><template v-if="!campaignForm.id"><a-form-item label="教学班" required><a-select v-model:value="campaignForm.class_ids" mode="multiple" placeholder="选择一个或多个教学班" :options="classOptions" @change="changeCampaignClasses"/></a-form-item><a-spin :spinning="campaignOptionsLoading"><a-form-item v-for="id in campaignForm.class_ids" :key="id" :label="`${session.classes.find(item=>item.id===id)?.name||'教学班'}的个人作业`" required><a-select v-model:value="campaignAssignmentIds[id]" placeholder="选择个人作业" :options="(campaignAssignmentsByClass[id]||[]).map(item=>({value:item.id,label:item.title}))" :not-found-content="'暂无可开启互评的个人作业'"/></a-form-item></a-spin></template><a-alert v-if="campaignForm.has_reviews" type="warning" show-icon message="已有评价，评分维度和权重已锁定"/><a-form-item label="评分维度" required><div v-for="(item,index) in rubric" :key="index" class="rubric-row"><a-input v-model:value="item.label" :disabled="campaignForm.has_reviews" placeholder="维度名称"/><a-input-number v-model:value="item.weight" :disabled="campaignForm.has_reviews" :min="1" :max="100" addon-after="%"/><a-button danger type="text" :disabled="campaignForm.has_reviews||rubric.length===1" @click="rubric.splice(index,1)">删除</a-button></div><a-button v-if="!campaignForm.has_reviews" type="dashed" block @click="rubric.push({label:'',weight:10})"><PlusOutlined/> 添加维度</a-button></a-form-item><a-form-item label="公开时间"><a-input v-model:value="campaignForm.publish_at" type="datetime-local"/></a-form-item><a-form-item label="截止时间" required><a-input v-model:value="campaignForm.due_at" type="datetime-local"/></a-form-item><a-form-item label="评语最少字数"><a-input-number v-model:value="campaignForm.comment_min_length" :min="0"/></a-form-item><a-checkbox v-model:checked="campaignForm.require_all">要求评价全部组员</a-checkbox><br><a-checkbox v-model:checked="campaignForm.allow_update">截止前允许修改</a-checkbox></a-form></a-modal>
    <a-modal v-model:open="selectedCampaign" :title="selectedCampaign?.assignment_title" :footer="null" width="760px"><template v-if="role==='STUDENT'"><a-alert class="review-scope-alert" type="info" show-icon message="互评范围：同一小组内的其他成员" description="只能评价对方在本活动所关联个人作业中的最新正式提交。"/><a-empty v-if="!candidates.length" description="本组暂无其他成员，请先确认两个账号已加入同一小组"/><a-list :data-source="candidates"><template #renderItem="{item}"><a-list-item><a-list-item-meta :title="item.name" :description="item.submitted?`已正式提交 V${item.version_no} · ${formatTime(item.submitted_at)}`:'该成员尚未正式提交本次互评关联的作业'"/><a-space><a-button v-for="file in item.files" :key="file.id" type="link" :href="`/api/v1/files/${file.id}/preview`" target="_blank">{{file.name}}</a-button><a-tag v-if="!item.submitted" color="warning">暂不可评价</a-tag><a-button v-else-if="!item.reviewed||selectedCampaign.allow_update" type="primary" @click="startReview(item)">{{item.reviewed?'修改评价':'评价作品'}}</a-button><a-tag v-else color="green">已评价</a-tag></a-space></a-list-item></template></a-list></template><template v-else><div class="detail-metrics"><div><span>有效评价</span><strong>{{campaignStats?.review_count||0}}</strong></div><div><span>参与人数</span><strong>{{campaignStats?.reviewer_count||0}}</strong></div><div><span>未完成评价人数</span><strong>{{campaignStats?.uncompleted_reviewer_count||0}}</strong></div><div><span>平均分</span><strong>{{campaignStats?.average_score??'-'}}</strong></div></div><a-table :data-source="campaignReviews" row-key="id" size="small"><a-table-column title="评价人" data-index="reviewer_name"/><a-table-column title="被评价人" data-index="reviewee_name"/><a-table-column title="得分" data-index="total_score"/><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="操作"><template #default="{record}"><a-tooltip v-if="record.status==='VALID'" title="作废评价"><a-button danger type="text" shape="circle" @click="openInvalidate(record)"><DeleteOutlined/></a-button></a-tooltip></template></a-table-column></a-table></template></a-modal>
    <a-modal v-model:open="modals.review" title="评价作品" @ok="submitReview"><a-form layout="vertical"><a-form-item v-for="dim in selectedCampaign?.rubric||[]" :key="dim.key" :label="`${dim.label}（权重 ${dim.weight}%）`"><a-slider v-model:value="reviewForm.scores[dim.key]" :min="0" :max="100"/></a-form-item><a-form-item label="具体评语" required><a-textarea v-model:value="reviewForm.comment" :rows="4" :maxlength="2000" show-count/></a-form-item><a-statistic title="加权总分" :value="(selectedCampaign?.rubric||[]).reduce((n,x)=>n+(reviewForm.scores[x.key]||0)*x.weight/100,0)" :precision="2"/></a-form></a-modal>
    <a-modal v-model:open="selectedGrade" :title="selectedGrade ? `${selectedGrade.assignment_title} · 修订记录` : '修订记录'" :footer="null"><a-empty v-if="!gradeRevisions.length" description="暂无修订记录"/><a-timeline v-else><a-timeline-item v-for="item in gradeRevisions" :key="item.id"><strong>{{item.score}} 分 · {{statusLabel(item.status)}}</strong><p>{{item.comment||'无评语'}}</p><span>{{item.reason||'未填写修改原因'}} · {{formatTime(item.created_at)}}</span></a-timeline-item></a-timeline></a-modal>
    <a-modal v-model:open="modals.grade" title="录入成绩" @ok="saveGrade"><a-form layout="vertical"><a-form-item label="作业" required><a-select v-model:value="gradeForm.assignment_id" :options="assignments.map(x=>({value:x.id,label:x.title}))" @change="gradeForm.subject_user_id='';gradeForm.subject_team_id=''"/></a-form-item><a-alert v-if="gradeForm.publish&&gradePublishPreview" class="grade-preview" type="info" show-icon :message="`${gradePublishPreview.assignment}：已评分 ${gradePublishPreview.scored}，未评分 ${gradePublishPreview.pending}`" :description="`当前成绩范围：${gradePublishPreview.range}`"/><a-form-item v-if="gradeAssignment?.submitter_type==='INDIVIDUAL'" label="学生" required><a-select v-model:value="gradeForm.subject_user_id" :options="members.map(x=>({value:x.id,label:`${x.name}（${x.student_no}）`}))"/></a-form-item><a-form-item v-else-if="gradeAssignment" label="小组" required><a-select v-model:value="gradeForm.subject_team_id" :options="teams.map(x=>({value:x.id,label:x.name}))"/></a-form-item><a-form-item label="成绩"><a-input-number v-model:value="gradeForm.score" :min="0" :max="100"/></a-form-item><a-form-item label="评语"><a-textarea v-model:value="gradeForm.comment" :rows="4"/></a-form-item><a-form-item v-if="gradeForm.publish" label="修改原因"><a-input v-model:value="gradeForm.reason" placeholder="首次发布可留空"/></a-form-item><a-checkbox v-model:checked="gradeForm.publish">发布给学生</a-checkbox></a-form></a-modal>
    <a-modal v-model:open="modals.topicDecision" title="驳回选题" ok-text="确认驳回" @ok="rejectTopic"><a-form layout="vertical"><a-form-item label="驳回原因" required><a-textarea v-model:value="topicDecisionForm.reason" :rows="3" placeholder="请说明需要修改的内容"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.invalidate" title="作废评价" @ok="invalidateReview"><a-form layout="vertical"><a-form-item label="原因" required><a-textarea v-model:value="invalidReason" :rows="3"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.password" title="修改密码" @ok="changePassword"><a-form layout="vertical"><a-form-item label="当前密码"><a-input-password v-model:value="passwordForm.current_password"/></a-form-item><a-form-item label="新密码"><a-input-password v-model:value="passwordForm.new_password"/></a-form-item></a-form></a-modal>
  </a-layout>
</template>
