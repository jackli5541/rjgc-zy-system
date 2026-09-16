<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { ArrowLeftOutlined, BellOutlined, BoldOutlined, BookOutlined, CheckCircleOutlined, CloseOutlined, CodeOutlined, DashboardOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, EyeOutlined, FileTextOutlined, FormOutlined, InboxOutlined, KeyOutlined, LeftOutlined, LinkOutlined, LogoutOutlined, OrderedListOutlined, PlusOutlined, RedoOutlined, RightOutlined, SettingOutlined, TeamOutlined, TrophyOutlined, UnorderedListOutlined, UploadOutlined, UserOutlined } from '@ant-design/icons-vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
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
const gradeAssignments = ref([])
const selectedGradeAssignmentId = ref('')
const gradeDetail = ref(null)
const gradeRevisions = ref([])
const selectedGrade = ref(null)
const notifications = ref([])
const audits = ref([])
const selectedTeam = ref(null)
const selectedAssignment = ref(null)
const selectedSubmission = ref(null)
const selectedCampaign = ref(null)
const reviewTask = ref(null)
const campaignStats = ref(null)
const campaignReviews = ref([])
const receivedReviews = ref([])
const sentReviews = ref([])
const classJoinRequests = ref([])
const assignmentAttachments = ref([])
const reviewCriteriaFiles = ref([])
const pendingAssignmentFiles = ref([])
const pendingAutoReviewFiles = ref([])
const draftFiles = ref([])
const boardFilter = ref('ALL')
const boardQuery = ref('')
const boardTeamFilter = ref('ALL')
const assignmentDetailTab = ref('details')
const noticesOpen = ref(false)
const modals = reactive({ class: false, import: false, member: false, team: false, assignment: false, gradePublish: false, password: false, invalidate: false, joinClass: false, topicDecision: false })
const classForm = reactive({ id: '', version: 1, semester: '', name: '', team_deadline: '', max_team_members: 5, topic_public: false, invite_requires_approval: true })
const joinClassForm = reactive({ invite_code: '' })
const memberForm = reactive({ id: '', student_no: '', name: '' })
const teamForm = reactive({ name: '', open_recruitment: true })
const assignmentForm = reactive({ id: '', version: 1, has_submissions: false, class_ids: [], title: '', description: '', submitter_type: 'INDIVIDUAL', starts_at: '', due_at: '', allow_late: false, publish: true, auto_review_enabled: false, auto_review_mode: 'TEAM', auto_review_criteria_text: '', auto_review_due_at: '' })
const reviewForm = reactive({ score: 0, comment: '', reviewee_id: '', scores: {} })
const selectedReview = ref(null)
const invalidReason = ref('')
const topicForm = reactive({ name: '', description: '' })
const topicDecisionForm = reactive({ id: '', reason: '' })
const passwordForm = reactive({ current_password: '', new_password: '' })
const gradePublishReason = ref('')
const inviteTarget = ref('')
const importState = reactive({ file: null, preview: null, result: null, step: 0, loading: false })
const filePreview = reactive({ open: false, files: [], index: 0, url: '', loading: false, error: '' })
let gateTimer
let previewLoadSequence = 0

const descriptionEditor = useEditor({
  content: '',
  extensions: [StarterKit.configure({ link: { openOnClick: false } })],
  onUpdate: ({ editor }) => { assignmentForm.description = editor.getHTML() }
})

const role = computed(() => session.user?.role)
const classId = computed(() => session.classId)
const view = computed(() => route.name === 'assignment-detail' ? 'assignment-detail' : route.name === 'review-detail' ? 'review-detail' : route.name === 'grade-detail' ? 'grade-detail' : route.params.view || 'overview')
const detailId = computed(() => route.params.id)
const navView = computed(() => view.value === 'assignment-detail' ? 'assignments' : view.value === 'review-detail' ? 'reviews' : view.value === 'grade-detail' ? 'grades' : view.value)
const activeClasses = computed(() => session.classes.filter(item => item.status === 'ACTIVE'))
const classOptions = computed(() => activeClasses.value.map(item => ({ value: item.id, label: `${item.semester} · ${item.name}` })))
const currentTeam = computed(() => teams.value.find(item => item.id === session.context?.team_membership?.team_id))
const filteredMembers = computed(() => {
  const query = memberQuery.value.trim().toLocaleLowerCase()
  return members.value.filter(item => {
    const matchesQuery = !query || `${item.student_no} ${item.name} ${item.team || ''}`.toLocaleLowerCase().includes(query)
    return matchesQuery
  })
})
const boardTeamOptions = computed(() => {
  return [{ value: 'ALL', label: '全部小组' }, { value: 'NONE', label: '未分组' }, ...teams.value.map(item => ({ value: item.id, label: item.name }))]
})
const filteredBoard = computed(() => (selectedAssignment.value?.board || []).filter(item => {
  const q = boardQuery.value.trim().toLocaleLowerCase()
  const matchesQuery = !q || `${item.owner || ''} ${item.student_no || ''}`.toLocaleLowerCase().includes(q)
  const matchesTeam = boardTeamFilter.value === 'ALL' || (boardTeamFilter.value === 'NONE' ? !item.team_id : item.team_id === boardTeamFilter.value)
  const matchesStatus = boardFilter.value === 'ALL' || (boardFilter.value === 'LATE' ? item.is_late : boardFilter.value === item.status)
  return matchesQuery && matchesTeam && matchesStatus
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
const assignmentSubmitted = computed(() => selectedAssignment.value?.submission?.status === 'SUBMITTED')
const assignmentBeforeDue = computed(() => Boolean(selectedAssignment.value && new Date(selectedAssignment.value.due_at) > new Date()))
const assignmentIsUpdate = computed(() => assignmentSubmitted.value && assignmentBeforeDue.value)
const teacherSubmissionSummary = computed(() => {
  const board = selectedAssignment.value?.board || []
  const submitted = board.filter(item => item.status === 'SUBMITTED')
  return {
    total: board.length,
    submitted: submitted.length,
    pending: board.length - submitted.length,
    late: submitted.filter(item => item.is_late).length
  }
})
const canSubmitAssignment = computed(() => {
  const assignment = selectedAssignment.value
  if (!assignment) return false
  if (assignment.status !== 'PUBLISHED') return false
  return new Date(assignment.due_at) > new Date() || (!assignmentSubmitted.value && assignment.allow_late)
})
const campaignEnded = computed(() => Boolean(selectedCampaign.value && (selectedCampaign.value.status !== 'ACTIVE' || new Date(selectedCampaign.value.due_at) <= new Date())))
const currentCampaignReviews = computed(() => receivedReviews.value.filter(item => item.campaign_id === selectedCampaign.value?.id))
const activePreviewFile = computed(() => filePreview.files[filePreview.index] || null)
const activePreviewIsImage = computed(() => /\.(png|jpe?g|gif|webp)$/i.test(activePreviewFile.value?.name || ''))
const reviewConfigEditable = computed(() => Boolean(selectedAssignment.value && selectedAssignment.value.status !== 'CLOSED' && new Date(selectedAssignment.value.due_at) > new Date() && !selectedCampaign.value))
const studentLatestGrade = computed(() => grades.value.find(item => item.status === 'PUBLISHED'))
const menu = computed(() => {
  if (role.value === 'TEACHER') return [
    ['overview', DashboardOutlined, '总览'], ['classes', BookOutlined, '教学班'], ['teams', TeamOutlined, '小组与选题'],
    ['assignments', FileTextOutlined, '作业管理'], ['grades', TrophyOutlined, '成绩与导出'], ['system', SettingOutlined, '系统与审计']
  ]
  if (session.teamGate) return [['teams', TeamOutlined, '加入小组']]
  return [['overview', DashboardOutlined, '总览'], ['teams', TeamOutlined, '我的小组'], ['assignments', FileTextOutlined, '我的作业'], ['reviews', FormOutlined, '作品互评'], ['grades', TrophyOutlined, '成绩与反馈']]
})

function iso(value) { return value ? new Date(value).toISOString() : null }
function localDateTime(value) { if (!value) return ''; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-' }
function assignmentStateClass(item) {
  if (role.value !== 'STUDENT') return ''
  if (item.submission_status === 'SUBMITTED') return 'task-completed'
  return new Date(item.due_at) <= new Date() ? 'task-overdue' : ''
}
function campaignStateClass(item) {
  if (role.value !== 'STUDENT') return ''
  if (['COMPLETED', 'SKIPPED'].includes(item.allocation_status)) return 'task-completed'
  return new Date(item.due_at) <= new Date() ? 'task-overdue' : ''
}
const statusLabels = { ACTIVE: '进行中', ARCHIVED: '已归档', PENDING: '待处理', PENDING_REVIEW: '待处理', PENDING_COEFFICIENT: '待填系数', CHANGED: '有未发布修改', APPROVED: '已通过', REJECTED: '已拒绝', CANCELLED: '已取消', DRAFT: '待发布', PUBLISHED: '已发布', SUBMITTED: '已提交', RETRACTED: '已撤回', VALID: '有效', INVALID: '已作废', CLOSED: '已结束', NOT_SUBMITTED: '未提交', LEFT: '已退出', DISBANDED: '已解散', NOT_STARTED: '未开始' }
const roleLabels = { LEADER: '组长', MEMBER: '组员', TEACHER: '教师', STUDENT: '学生' }
const objectLabels = { user: '用户', class: '教学班', class_join_request: '入班申请', team: '小组', team_request: '组队申请', topic: '选题', assignment: '作业', submission: '作业提交', review_campaign: '互评活动', peer_review: '作品评价', grade: '成绩' }
const actionLabels = { PASSWORD_CHANGED: '修改密码', PASSWORD_RESET: '重置密码', CLASS_CREATED: '创建教学班', CLASS_UPDATED: '更新教学班', CLASS_DELETED: '删除教学班', CLASS_JOIN_REQUESTED: '申请加入教学班', CLASS_JOINED_BY_INVITE: '通过邀请码入班', CLASS_JOIN_APPROVED: '同意入班申请', CLASS_JOIN_REJECTED: '拒绝入班申请', ROSTER_IMPORTED: '导入学生名单', CLASS_MEMBER_ADDED: '添加班级成员', CLASS_MEMBER_UPDATED: '更新成员信息', CLASS_MEMBER_REMOVED: '移出班级成员', TEAM_CREATED: '创建小组', TEAM_REQUEST_DECIDED: '处理组队申请', TEAM_INVITATION_RESPONDED: '回应小组邀请', TEAM_LEADER_TRANSFERRED: '移交组长', TEAM_LEFT: '退出小组', TEAM_DISBANDED: '解散小组', TEAM_MEMBER_REMOVED: '移出小组成员', TOPIC_SUBMITTED: '提交选题', TOPIC_DECIDED: '审核选题', ASSIGNMENT_CREATED: '创建作业', ASSIGNMENT_UPDATED: '更新作业', ASSIGNMENT_PUBLISHED: '发布作业', ASSIGNMENT_RETRACTED: '撤回作业', ASSIGNMENT_CLOSED: '提前截止作业', ASSIGNMENT_DELETED: '删除作业', SUBMISSION_CREATED: '提交作业', SUBMISSION_RETRACTED: '撤回作业', SUBMISSIONS_EXPORTED: '导出作业', REVIEW_CAMPAIGN_CREATED: '创建互评活动', REVIEW_CAMPAIGN_CLOSED: '提前截止互评', PEER_REVIEW_SUBMITTED: '提交作品评价', PEER_REVIEW_UPDATED: '更新作品评价', PEER_REVIEW_INVALIDATED: '作废作品评价', PEER_GRADES_GENERATED: '生成互评成绩', GRADE_COEFFICIENT_UPDATED: '更新小组系数', GRADES_PUBLISHED: '发布成绩' }
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
    if (view.value === 'assignment-detail') {
      assignments.value = (await api(`/assignments?class_id=${classId.value}`)).items
      const assignment = assignments.value.find(item => item.id === detailId.value)
      if (!assignment) { message.error('作业不存在或无权查看'); await router.replace('/assignments') }
      else {
        const allowedTabs = role.value === 'TEACHER' ? ['details', 'submission', 'reviews', 'grades'] : ['details', 'submission']
        assignmentDetailTab.value = allowedTabs.includes(route.query.tab) ? route.query.tab : 'details'
        await loadAssignmentDetail(assignment)
      }
    }
    if (view.value === 'reviews') {
      if (role.value === 'TEACHER') { await router.replace('/assignments'); return }
      campaigns.value = (await api(`/review-campaigns?class_id=${classId.value}`)).items
      const [received, sent] = await Promise.all([api(`/peer-reviews/received?class_id=${classId.value}`), api(`/peer-reviews/sent?class_id=${classId.value}`)])
      receivedReviews.value = received.items; sentReviews.value = sent.items
    }
    if (view.value === 'review-detail') {
      const [campaignData, received, sent] = await Promise.all([
        api(`/review-campaigns?class_id=${classId.value}`),
        role.value === 'STUDENT' ? api(`/peer-reviews/received?class_id=${classId.value}`) : Promise.resolve({ items: [] }),
        role.value === 'STUDENT' ? api(`/peer-reviews/sent?class_id=${classId.value}`) : Promise.resolve({ items: [] })
      ])
      campaigns.value = campaignData.items; receivedReviews.value = received.items; sentReviews.value = sent.items
      const campaign = campaigns.value.find(item => item.id === detailId.value)
      if (!campaign) { message.error('互评活动不存在或无权查看'); await router.replace('/reviews') }
      else if (role.value === 'TEACHER') await router.replace({ name: 'assignment-detail', params: { id: campaign.assignment_id }, query: { tab: 'reviews' } })
      else await loadCampaignDetail(campaign)
    }
    if (view.value === 'grades') {
      if (role.value === 'TEACHER') gradeAssignments.value = (await api(`/grades/assignments?class_id=${classId.value}`)).items
      else grades.value = (await api(`/grades?class_id=${classId.value}`)).items
    }
    if (view.value === 'grade-detail') {
      if (role.value !== 'TEACHER') { await router.replace('/grades'); return }
      await router.replace({ name: 'assignment-detail', params: { id: detailId.value }, query: { tab: 'grades' } })
      return
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
function defaultClassSelection() {
  if (activeClasses.value.some(item => item.id === classId.value)) return [classId.value]
  return activeClasses.value[0] ? [activeClasses.value[0].id] : []
}
function openAssignmentCreate() {
  Object.assign(assignmentForm, { id: '', version: 1, has_submissions: false, class_ids: defaultClassSelection(), title: '', description: '', submitter_type: 'INDIVIDUAL', starts_at: '', due_at: '', allow_late: false, publish: false, auto_review_enabled: false, auto_review_mode: 'TEAM', auto_review_criteria_text: '', auto_review_due_at: '' }); pendingAssignmentFiles.value = []; pendingAutoReviewFiles.value = []; descriptionEditor.value?.commands.setContent('', { emitUpdate: false }); modals.assignment = true
}
function openAssignmentEdit() {
  const item = selectedAssignment.value
  Object.assign(assignmentForm, { id: item.id, version: item.version, has_submissions: (item.board || []).some(record => record.status === 'SUBMITTED'), class_ids: [item.class_id], title: item.title, description: item.description, submitter_type: item.submitter_type, starts_at: localDateTime(item.starts_at), due_at: localDateTime(item.due_at), allow_late: item.allow_late, publish: item.status === 'PUBLISHED', auto_review_enabled: item.auto_review_enabled, auto_review_mode: item.auto_review_mode || 'TEAM', auto_review_criteria_text: item.auto_review_criteria_text || '', auto_review_due_at: localDateTime(item.auto_review_due_at) })
  descriptionEditor.value?.commands.setContent(item.description || '', { emitUpdate: false }); pendingAssignmentFiles.value = []; pendingAutoReviewFiles.value = []; modals.assignment = true
}
function setDescriptionLink() {
  const current = descriptionEditor.value?.getAttributes('link').href || ''
  const href = window.prompt('链接地址', current)
  if (href === null) return
  if (!href.trim()) descriptionEditor.value?.chain().focus().unsetLink().run()
  else descriptionEditor.value?.chain().focus().extendMarkRange('link').setLink({ href: href.trim() }).run()
}
function queueAssignmentAttachment(file) { pendingAssignmentFiles.value.push(file); return false }
function removePendingAssignmentAttachment(index) { pendingAssignmentFiles.value.splice(index, 1) }
function queueAutoReviewAttachment(file) { pendingAutoReviewFiles.value.push(file); return false }
function toggleAutoReview() { if (assignmentForm.auto_review_enabled) assignmentForm.submitter_type = 'INDIVIDUAL' }
async function createAssignment(publishRequested = false) {
  if (!assignmentForm.id && !assignmentForm.class_ids.length) return message.warning('请至少选择一个教学班')
  if (!assignmentForm.due_at) return message.warning('请选择截止时间')
  if (assignmentForm.starts_at && new Date(assignmentForm.starts_at) >= new Date(assignmentForm.due_at)) return message.warning('开始时间必须早于截止时间')
  if (assignmentForm.auto_review_enabled) {
    if (!assignmentForm.auto_review_due_at || new Date(assignmentForm.auto_review_due_at) <= new Date(assignmentForm.due_at)) return message.warning('互评截止时间必须晚于作业截止时间')
    if (!assignmentForm.auto_review_criteria_text.trim() && !pendingAutoReviewFiles.value.length && (!assignmentForm.id || !reviewCriteriaFiles.value.length)) return message.warning('自动互评标准文字和附件至少提供一种')
  }
  if (assignmentForm.id) {
    await action(async () => {
      for (const file of pendingAutoReviewFiles.value) {
        const body = new FormData(); body.append('file', file)
        await api(`/assignments/${assignmentForm.id}/files?purpose=REVIEW_CRITERIA`, { method: 'POST', body })
      }
      const payload = { title: assignmentForm.title, description: assignmentForm.description, submitter_type: assignmentForm.submitter_type, starts_at: iso(assignmentForm.starts_at), due_at: iso(assignmentForm.due_at), allow_late: assignmentForm.allow_late, version: assignmentForm.version }
      if (reviewConfigEditable.value) Object.assign(payload, { auto_review_enabled: assignmentForm.auto_review_enabled, auto_review_mode: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_mode : null, auto_review_criteria_text: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_criteria_text : '', auto_review_due_at: assignmentForm.auto_review_enabled ? iso(assignmentForm.auto_review_due_at) : null })
      await api(`/assignments/${assignmentForm.id}`, { method: 'PATCH', body: JSON.stringify(payload) }); modals.assignment = false
      pendingAutoReviewFiles.value = []
    }, '作业已更新')
    return
  }
  const count = assignmentForm.class_ids.length
  try {
    const created = await api('/assignments/bulk', { method: 'POST', body: JSON.stringify({ ...assignmentForm, publish: false, starts_at: iso(assignmentForm.starts_at), due_at: iso(assignmentForm.due_at), auto_review_due_at: iso(assignmentForm.auto_review_due_at) }) })
    const failed = []
    for (const assignment of created.items) {
      for (const file of pendingAssignmentFiles.value) {
        try {
          const body = new FormData(); body.append('file', file)
          await api(`/assignments/${assignment.id}/files`, { method: 'POST', body })
        } catch (error) { failed.push(`${assignment.title}：${file.name}（${error.message}）`) }
      }
      for (const file of pendingAutoReviewFiles.value) {
        try {
          const body = new FormData(); body.append('file', file)
          await api(`/assignments/${assignment.id}/files?purpose=REVIEW_CRITERIA`, { method: 'POST', body })
        } catch (error) { failed.push(`${assignment.title}：互评标准 ${file.name}（${error.message}）`) }
      }
    }
    if (!failed.length && publishRequested) await Promise.all(created.items.map(item => api(`/assignments/${item.id}/publish`, { method: 'POST' })))
    pendingAssignmentFiles.value = []; pendingAutoReviewFiles.value = []; modals.assignment = false; await session.refreshClasses(classId.value); await loadView()
    if (failed.length) message.warning(`草稿已保留，${failed.length} 个附件上传失败，可在作业详情中重试后发布`)
    else message.success(publishRequested ? `已向 ${count} 个教学班发布作业` : `已为 ${count} 个教学班保存草稿`)
  } catch (error) { message.error(error.message) }
}
async function loadAssignmentDetail(item) {
  selectedAssignment.value = item; selectedSubmission.value = null; selectedCampaign.value = null; campaignStats.value = null; campaignReviews.value = []; gradeDetail.value = null; boardFilter.value = 'ALL'; boardTeamFilter.value = 'ALL'; boardQuery.value = ''
  const [files, campaignData] = await Promise.all([
    api(`/assignments/${item.id}/files`),
    role.value === 'TEACHER' ? api(`/review-campaigns?class_id=${item.class_id}`) : Promise.resolve({ items: [] })
  ])
  assignmentAttachments.value = files.attachments; reviewCriteriaFiles.value = files.review_criteria || []; draftFiles.value = files.drafts
  if (role.value === 'STUDENT') {
    item.submission = await api(`/assignments/${item.id}/submission`)
  }
  else {
    const [boardData, teamData] = await Promise.all([api(`/assignments/${item.id}/submissions`), api(`/teams?class_id=${item.class_id}`)])
    item.board = boardData.items; teams.value = teamData.items
    campaigns.value = campaignData.items
    const campaign = campaigns.value.find(record => record.assignment_id === item.id)
    if (campaign) {
      await loadCampaignDetail(campaign)
      if (campaign.grades_generated_at) await loadGradeAssignment(item.id)
    }
  }
}
function changeAssignmentDetailTab(key) {
  assignmentDetailTab.value = key
  router.replace({ name: 'assignment-detail', params: { id: selectedAssignment.value.id }, query: key === 'details' ? {} : { tab: key } })
}
async function openAssignment(item) {
  await router.push(`/assignments/${item.id}`)
}
async function uploadFile({ file, onSuccess, onError }) {
  try {
    const body = new FormData(); body.append('file', file); const saved = await api(`/assignments/${selectedAssignment.value.id}/files`, { method: 'POST', body })
    if (role.value === 'TEACHER') assignmentAttachments.value.push(saved)
    else draftFiles.value.push(saved)
    onSuccess(saved)
  } catch (e) { onError(e); message.error(e.message) }
}
async function uploadReviewCriteria({ file, onSuccess, onError }) {
  try {
    const body = new FormData(); body.append('file', file)
    const saved = await api(`/assignments/${selectedAssignment.value.id}/files?purpose=REVIEW_CRITERIA`, { method: 'POST', body })
    reviewCriteriaFiles.value.push(saved); onSuccess(saved)
  } catch (error) { onError(error); message.error(error.message) }
}
function deleteDraft(file) {
  const submitted = Boolean(file.submitted)
  Modal.confirm({
    title: submitted ? '从待更新附件中移除？' : '确认删除文件？',
    content: submitted ? '移除后需要点击“更新提交”生成新版本，历史提交记录不受影响。' : '删除后无法恢复。',
    okText: submitted ? '确认移除' : '确认删除',
    cancelText: '取消',
    onOk: () => action(async () => { await api(`/files/${file.id}`, { method: 'DELETE' }); await loadAssignmentDetail(selectedAssignment.value) }, submitted ? '已移除，请点击“更新提交”' : '文件已删除')
  })
}
async function submitAssignment() {
  if (!draftFiles.value.length) return message.warning('请先上传附件')
  const updating = assignmentIsUpdate.value
  Modal.confirm({ title: updating ? '确认更新提交？' : '确认正式提交？', content: `将以当前 ${draftFiles.value.length} 个附件${updating?'覆盖原提交内容':'完成正式提交'}。`, okText: updating ? '确认更新' : '确认提交', cancelText: '继续检查', onOk: async () => action(async () => { await api(`/assignments/${selectedAssignment.value.id}/submission`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({}) }); await loadAssignmentDetail(selectedAssignment.value) }, updating ? '提交已更新' : '提交成功') })
}
function openSubmissionDetail(record) { selectedSubmission.value = record }
async function publishAssignment() { await action(() => api(`/assignments/${selectedAssignment.value.id}/publish`, { method: 'POST' }), '作业已发布') }
function retractAssignment() {
  Modal.confirm({ title: '确认撤回发布？', content: '撤回后学生将不能查看或提交，作业会回到草稿状态。', okText: '确认撤回', okType: 'danger', cancelText: '取消', onOk: () => action(() => api(`/assignments/${selectedAssignment.value.id}/retract`, { method: 'POST' }), '作业已撤回') })
}
function closeAssignment() {
  Modal.confirm({ title: '确认提前截止？', content: '截止后学生将不能继续上传或提交，已有提交和历史记录会保留。', okText: '确认截止', okType: 'danger', cancelText: '取消', onOk: () => action(() => api(`/assignments/${selectedAssignment.value.id}/close`, { method: 'POST' }), '作业已提前截止') })
}
function deleteAssignment() {
  Modal.confirm({ title: '确认永久删除作业？', content: '作业、附件、提交记录、关联互评和成绩都会从数据库中永久删除，且无法恢复。', okText: '永久删除', okType: 'danger', cancelText: '取消', onOk: () => action(async () => { await api(`/assignments/${selectedAssignment.value.id}`, { method: 'DELETE' }); selectedAssignment.value = null; await router.replace('/assignments') }, '作业已删除') })
}
async function loadCampaignDetail(item) {
  selectedCampaign.value = item; reviewTask.value = null
  if (role.value === 'STUDENT') {
    if (new Date(item.due_at) > new Date()) {
      reviewTask.value = await api(`/review-campaigns/${item.id}/assignment`)
      Object.assign(reviewForm, { score: reviewTask.value?.review?.score || 0, comment: reviewTask.value?.review?.comment || '', reviewee_id: '', scores: {} })
    }
  }
  else {
    const [stats, reviews] = await Promise.all([api(`/review-campaigns/${item.id}/stats`), api(`/review-campaigns/${item.id}/reviews`)])
    campaignStats.value = stats; campaignReviews.value = reviews.items
  }
}
async function openCampaign(item) {
  if (role.value === 'STUDENT') { await router.push(`/reviews/${item.id}`); return }
  await loadCampaignDetail(item)
}
function closeCampaign() {
  Modal.confirm({ title: '确认提前截止互评？', content: '截止后学生不能继续提交评价，已有评价和统计会保留。', okText: '确认截止', okType: 'danger', cancelText: '取消', onOk: () => action(async () => {
    const result = await api(`/review-campaigns/${selectedCampaign.value.id}/close`, { method: 'POST' })
    Object.assign(selectedCampaign.value, result)
    await Promise.all([loadCampaignDetail(selectedCampaign.value), loadGradeAssignment(result.assignment_id || selectedAssignment.value.id)])
  }, '互评已提前截止，成绩草稿已生成') })
}
async function submitReview() {
  const payload = { score: reviewForm.score, comment: reviewForm.comment }
  const updating = reviewTask.value?.status === 'COMPLETED'
  await action(async () => { await api(`/review-campaigns/${selectedCampaign.value.id}/reviews`, { method: 'POST', body: JSON.stringify(payload) }); await loadCampaignDetail(selectedCampaign.value) }, updating ? '评价已更新' : '评价已提交')
}
function openInvalidate(item) { selectedReview.value = item; invalidReason.value = ''; modals.invalidate = true }
async function invalidateReview() { await action(async () => { await api(`/peer-reviews/${selectedReview.value.id}/invalidate`, { method: 'POST', body: JSON.stringify({ reason: invalidReason.value }) }); modals.invalidate = false; await loadCampaignDetail(selectedCampaign.value) }, '评价已作废') }
async function readAll() { await action(() => api('/notifications/read', { method: 'POST' }), '已全部标为已读'); noticesOpen.value = false }
async function changePassword() { await action(async () => { await api('/auth/password', { method: 'POST', body: JSON.stringify(passwordForm) }); modals.password = false; await session.logout(); await router.replace('/login') }, '密码已修改，请重新登录') }
async function openGradeRevisions(item) { try { selectedGrade.value = item; gradeRevisions.value = (await api(`/grades/${item.id}/revisions`)).items } catch (e) { message.error(e.message) } }
async function loadGradeAssignment(id) { selectedGradeAssignmentId.value = id; gradeDetail.value = id ? await api(`/grades/assignments/${id}`) : null; gradeDetail.value?.groups.forEach(group => { group.input_value = group.draft_value }) }
async function saveCoefficient(group) {
  if (group.input_value === null || group.input_value === undefined || group.input_value === '') return message.warning('请输入非负小组系数')
  await action(async () => {
    await api(`/grades/assignments/${selectedGradeAssignmentId.value}/teams/${group.team_id}/coefficient`, { method: 'PATCH', body: JSON.stringify({ coefficient: group.input_value, version: group.version }) })
    await loadGradeAssignment(selectedGradeAssignmentId.value)
  }, `${group.team_name}系数已保存`)
}
function openGradePublish() { gradePublishReason.value = ''; modals.gradePublish = true }
async function publishGrades() {
  if (gradeDetail.value?.summary.changed && gradePublishReason.value.trim().length < 2) return message.warning('修改已发布成绩时请填写修改原因')
  await action(async () => {
    await api(`/grades/assignments/${selectedGradeAssignmentId.value}/publish`, { method: 'POST', body: JSON.stringify({ reason: gradePublishReason.value }) })
    modals.gradePublish = false; await loadGradeAssignment(selectedGradeAssignmentId.value)
  }, '成绩已发布')
}
async function logout() { try { await session.logout() } finally { await router.replace('/login') } }
function downloadExport(kind, format = 'xlsx') {
  const assignment = kind === 'grades' && selectedGradeAssignmentId.value ? `&assignment_id=${selectedGradeAssignmentId.value}` : ''
  window.location.href = `/api/v1/exports/${kind}.${format}?class_id=${classId.value}${assignment}`
}
function clearPreviewUrl() {
  if (filePreview.url) URL.revokeObjectURL(filePreview.url)
  filePreview.url = ''
}
async function loadFilePreview() {
  const requestSequence = ++previewLoadSequence
  clearPreviewUrl()
  filePreview.error = ''
  const file = activePreviewFile.value
  if (!file) return
  if (!file.previewable || file.download_only || (file.preview_status && file.preview_status !== 'READY')) {
    filePreview.loading = false
    filePreview.error = file.preview_error || '该文件格式暂不支持在线预览，可下载原文件查看。'
    return
  }
  filePreview.loading = true
  try {
    const response = await fetch(`/api/v1/files/${file.id}/preview`, { credentials: 'include' })
    if (response.status === 401) window.dispatchEvent(new CustomEvent('auth-expired'))
    if (!response.ok) {
      const type = response.headers.get('content-type') || ''
      const body = type.includes('json') ? await response.json() : await response.text()
      throw new Error(body?.message || body?.detail?.message || '文件预览加载失败')
    }
    const contentType = response.headers.get('content-type') || ''
    if (!contentType.startsWith('image/') && !contentType.includes('application/pdf') && !contentType.includes('text/html')) {
      throw new Error('该文件内容无法在浏览器中预览')
    }
    const objectUrl = URL.createObjectURL(await response.blob())
    if (requestSequence !== previewLoadSequence || !filePreview.open) { URL.revokeObjectURL(objectUrl); return }
    filePreview.url = objectUrl
  } catch (error) {
    if (requestSequence === previewLoadSequence) filePreview.error = error.message || '文件预览加载失败，请下载原文件查看。'
  } finally {
    if (requestSequence === previewLoadSequence) filePreview.loading = false
  }
}
function openFilePreview(file, files) {
  filePreview.files = [...(files || [])]
  filePreview.index = Math.max(0, filePreview.files.findIndex(item => item.id === file.id))
  filePreview.open = true
  loadFilePreview()
}
function switchFilePreview(step) {
  const next = filePreview.index + step
  if (next < 0 || next >= filePreview.files.length) return
  filePreview.index = next
  loadFilePreview()
}
function closeFilePreview() {
  previewLoadSequence += 1
  filePreview.open = false
  filePreview.loading = false
  filePreview.error = ''
  clearPreviewUrl()
}

async function pollGate() {
  if (!session.teamGate) return
  const before = session.teamGate
  await session.refreshContext()
  if (before && !session.teamGate) { message.success('已加入小组'); clearInterval(gateTimer); await router.replace('/overview') }
}

watch(() => route.fullPath, loadView)
watch(() => session.teamGate, required => { clearInterval(gateTimer); gateTimer = required ? setInterval(pollGate, 10000) : undefined })
onMounted(async () => { await loadView(); if (session.teamGate) gateTimer = setInterval(pollGate, 10000); window.addEventListener('focus', pollGate) })
onBeforeUnmount(() => { clearInterval(gateTimer); window.removeEventListener('focus', pollGate); closeFilePreview() })
</script>

<template>
  <a-layout v-if="session.user" class="app-shell">
    <a-layout-header class="app-header">
      <div class="header-toolbar">
        <div class="header-left"><div class="header-brand"><div class="brand-mark"><CodeOutlined /></div><strong>软件工程</strong></div><a-select v-if="session.classes.length" class="class-switch" :value="classId" :options="session.classes.map(x => ({value:x.id,label:`${x.semester} · ${x.name}`}))" @change="changeClass" /></div>
        <div class="header-right"><a-badge :count="notifications.filter(x=>!x.read).length" size="small"><a-button type="text" shape="circle" @click="noticesOpen=true"><BellOutlined /></a-button></a-badge><a-dropdown><div class="user-chip"><a-avatar :style="{background:role==='TEACHER'?'#7352bd':'#1769aa'}">{{ session.user.name.slice(0,1) }}</a-avatar><div class="user-meta"><strong>{{ session.user.name }}</strong><span>{{ role==='TEACHER'?'教师':'学生' }}</span></div></div><template #overlay><a-menu><a-menu-item @click="modals.password=true"><UserOutlined /> 修改密码</a-menu-item><a-menu-item @click="logout"><LogoutOutlined /> 退出登录</a-menu-item></a-menu></template></a-dropdown></div>
      </div>
      <nav class="top-nav" aria-label="主导航"><button v-for="item in menu" :key="item[0]" :class="{active:navView===item[0]}" @click="router.push('/'+item[0])"><component :is="item[1]" />{{ item[2] }}</button></nav>
    </a-layout-header>
    <a-layout-content class="app-content"><div class="content-wrap"><a-spin :spinning="loading">
      <template v-if="view==='overview'">
        <div class="page-title"><div><div class="eyebrow">{{ role==='TEACHER'?'教师工作台':'学生学习台' }}</div><h1>{{ session.context?.current_class?.name || '还没有教学班' }}</h1><p>{{ classId ? (role==='TEACHER'?'掌握教学班、小组和课程任务的整体进展。':'查看我的小组、待完成作业和课程反馈。') : (role==='TEACHER'?'创建教学班后即可导入学生并开展课程。':'使用教师提供的邀请码加入教学班。') }}</p></div><a-button v-if="role==='TEACHER'&&!classId" type="primary" @click="openClassCreate"><PlusOutlined /> 创建教学班</a-button></div>
        <a-empty v-if="!classId" description="暂无教学班"><a-button v-if="role==='STUDENT'" type="primary" @click="modals.joinClass=true">通过邀请码加入教学班</a-button></a-empty>
        <div v-else-if="role==='TEACHER'" class="stat-grid"><div class="stat-card"><UserOutlined class="stat-icon blue"/><div class="stat-body"><span>教学班人数</span><strong>{{ dashboard?.summary.member_count||0 }}<small>人</small></strong></div></div><div class="stat-card"><TeamOutlined class="stat-icon purple"/><div class="stat-body"><span>当前小组</span><strong>{{ dashboard?.summary.team_count||0 }}<small>组</small></strong></div></div><div class="stat-card"><FileTextOutlined class="stat-icon green"/><div class="stat-body"><span>进行中作业</span><strong>{{ dashboard?.summary.active_assignments||0 }}<small>项</small></strong></div></div><div class="stat-card"><CheckCircleOutlined class="stat-icon green"/><div class="stat-body"><span>最近未截止作业</span><strong>{{ dashboard?.summary.submission_rate||0 }}<small>%</small></strong><em>{{dashboard?.summary.submission_assignment_title||'暂无作业'}}</em></div></div><div class="stat-card"><FormOutlined class="stat-icon blue"/><div class="stat-body"><span>最近结束互评</span><strong>{{ dashboard?.summary.peer_review_rate||0 }}<small>%</small></strong><em>{{dashboard?.summary.peer_review_assignment_title||'暂无互评'}}</em></div></div></div>
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
        <div class="page-title"><div><div class="eyebrow">{{ role==='TEACHER'?'教学组织':session.teamGate?'开始课程前':'协作空间' }}</div><h1>{{ role==='TEACHER'?'小组与选题':session.teamGate?'加入小组':'我的小组' }}</h1><p>{{ role==='TEACHER'?'审核各组选题，查看成员配置并处理异常。':session.teamGate?'创建小组或申请加入已有小组。入组后将自动进入教学班首页。':'管理本组成员、邀请和选题信息。' }}</p></div><a-button v-if="role==='STUDENT'&&session.teamGate" type="primary" @click="modals.team=true"><PlusOutlined /> 创建小组</a-button></div>
        <a-alert v-if="session.teamGate" type="info" show-icon message="加入小组后解锁课程功能" class="soft-alert"/>
        <div v-if="role==='STUDENT'" class="team-grid"><a-card v-for="item in teams" :key="item.id" class="team-card" :bordered="false"><div class="team-card-top"><a-avatar shape="square">{{item.name.slice(0,1)}}</a-avatar><a-tag :color="item.open_recruitment?'blue':'default'">{{item.open_recruitment?'招募中':'未开放'}}</a-tag></div><h3>{{item.name}}</h3><p>{{item.topic?.name||(session.context?.current_class?.topic_public?'暂未提交选题':'选题未公开')}}</p><div class="team-card-meta"><span>{{item.member_count}} / {{item.max_members}} 人</span><span>组长：{{item.leader_name}}</span></div><a-divider/><a-space wrap><a-button v-if="session.teamGate&&item.open_recruitment" type="primary" ghost @click="applyTeam(item)">申请加入</a-button><a-button v-if="item.is_leader" type="primary" @click="openTeam(item)">{{item.topic?'修改选题':'提交选题'}}</a-button><a-button @click="openTeam(item)">查看详情</a-button></a-space></a-card><a-empty v-if="!teams.length" description="暂无小组，可创建第一个小组"/></div>
        <a-card v-else class="panel-card" :bordered="false"><a-table :data-source="teams" row-key="id"><a-table-column title="小组" data-index="name"/><a-table-column title="组长" data-index="leader_name"/><a-table-column title="人数"><template #default="{record}">{{record.member_count}} / {{record.max_members}}</template></a-table-column><a-table-column title="选题"><template #default="{record}">{{record.topic?.name||'-'}}</template></a-table-column><a-table-column title="操作"><template #default="{record}"><a-space><a-tooltip title="查看小组"><a-button type="text" shape="circle" @click="openTeam(record)"><EyeOutlined/></a-button></a-tooltip><a-tooltip v-if="record.topic?.status==='PENDING'" title="通过选题"><a-button type="text" shape="circle" @click="decideTopic(record,'APPROVED')"><CheckCircleOutlined/></a-button></a-tooltip><a-tooltip v-if="record.topic?.status==='PENDING'" title="退回选题"><a-button danger type="text" shape="circle" @click="decideTopic(record,'REJECTED')"><CloseOutlined/></a-button></a-tooltip></a-space></template></a-table-column></a-table></a-card>
        <a-card v-if="requests.length" class="panel-card request-card" title="入组申请与邀请" :bordered="false"><div v-for="item in requests" :key="item.id" class="request-row"><div><strong>{{item.is_incoming?item.applicant_name:item.team_name}}</strong><span>{{item.kind==='INVITATION'?'小组邀请':item.is_incoming?'申请加入你的小组':`申请状态：${statusLabel(item.status)}`}}</span></div><a-space v-if="item.is_incoming&&item.kind==='APPLICATION'&&item.status==='PENDING'"><a-button @click="decideRequest(item,'REJECTED')">拒绝</a-button><a-button type="primary" @click="decideRequest(item,'APPROVED')">同意</a-button></a-space><a-space v-else-if="item.kind==='INVITATION'&&!item.is_incoming&&item.status==='PENDING'"><a-button @click="respondInvitation(item,'REJECTED')">拒绝</a-button><a-button type="primary" @click="respondInvitation(item,'APPROVED')">接受</a-button></a-space><a-button v-else-if="!item.is_incoming&&item.status==='PENDING'" @click="cancelRequest(item)">取消申请</a-button><a-tag v-else>{{statusLabel(item.status)}}</a-tag></div></a-card>
      </template>

      <template v-else-if="view==='assignments'">
        <div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'教学任务':'学习任务'}}</div><h1>{{role==='TEACHER'?'作业管理':'我的作业'}}</h1><p>{{role==='TEACHER'?'发布作业、维护附件并查看全班提交情况。':'查看作业要求，管理草稿并完成正式提交。'}}</p></div><a-button v-if="role==='TEACHER'" type="primary" :disabled="!activeClasses.length" @click="openAssignmentCreate"><PlusOutlined /> 新建作业</a-button></div>
        <a-empty v-if="!assignments.length" description="暂无作业"/><a-card v-for="item in assignments" :key="item.id" class="assignment-row" :class="assignmentStateClass(item)" :bordered="false" @click="openAssignment(item)"><div class="assignment-icon blue"><FileTextOutlined/></div><div class="assignment-main"><div class="assignment-heading"><h3>{{item.title}}</h3><a-tag v-if="role==='STUDENT'&&item.submission_status==='SUBMITTED'">已完成</a-tag><a-tag v-else-if="role==='STUDENT'&&new Date(item.due_at)<=new Date()" color="error">已逾期</a-tag></div><div class="rich-text compact" v-html="item.description"></div><span>截止 {{formatTime(item.due_at)}}</span></div><div class="assignment-end"><a-tag>{{item.submitter_type==='INDIVIDUAL'?'个人作业':'小组作业'}}</a-tag><a-tag :color="item.status==='PUBLISHED'?'green':'default'">{{statusLabel(item.status)}}</a-tag></div></a-card>
      </template>

      <template v-else-if="view==='assignment-detail'&&selectedAssignment">
        <div class="page-title detail-title"><div><div class="eyebrow">作业详情</div><h1>{{selectedAssignment.title}}</h1><div class="assignment-title-meta"><a-tag color="blue">{{selectedAssignment.submitter_type==='INDIVIDUAL'?'个人作业':'小组作业'}}</a-tag><a-tag :color="selectedAssignment.status==='PUBLISHED'?'green':'default'">{{statusLabel(selectedAssignment.status)}}</a-tag><span>截止 {{formatTime(selectedAssignment.due_at)}}</span><a-tag v-if="selectedAssignment.allow_late">允许迟交</a-tag></div></div><a-button @click="router.push('/assignments')"><ArrowLeftOutlined/> 返回作业列表</a-button></div>
        <section class="assignment-workspace">
          <a-tabs :active-key="assignmentDetailTab" class="assignment-detail-tabs" @change="changeAssignmentDetailTab">
            <a-tab-pane key="details" :tab="role==='TEACHER'?'详情':'作业详情'">
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业说明</h2></div>
                <div class="rich-text detail-description" v-html="selectedAssignment.description"></div>
              </section>
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业资料</h2><a-space><span v-if="assignmentAttachments.length">{{assignmentAttachments.length}} 个附件</span><a-upload v-if="role==='TEACHER'" :custom-request="uploadFile"><a-button><UploadOutlined/> 上传作业附件</a-button></a-upload></a-space></div>
                <a-empty v-if="!assignmentAttachments.length" class="detail-empty" description="暂无作业资料"/>
                <div v-else class="assignment-file-list"><div v-for="file in assignmentAttachments" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,assignmentAttachments)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-space><a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip><a-tooltip v-if="role==='TEACHER'&&selectedAssignment.status==='DRAFT'" title="删除附件"><a-button danger type="text" shape="circle" @click="deleteDraft(file)"><DeleteOutlined/></a-button></a-tooltip></a-space></div></div>
              </section>
              <section v-if="role==='TEACHER'" class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业操作</h2></div>
                <a-space wrap><a-button @click="openAssignmentEdit"><EditOutlined/> 编辑作业</a-button><a-button v-if="selectedAssignment.status==='DRAFT'" type="primary" @click="publishAssignment">发布作业</a-button><a-button v-if="selectedAssignment.status==='PUBLISHED'&&new Date(selectedAssignment.due_at)>new Date()" danger @click="closeAssignment">提前截止</a-button><a-button v-if="['PUBLISHED','CLOSED'].includes(selectedAssignment.status)" danger @click="retractAssignment">撤回发布</a-button><a-button danger @click="deleteAssignment"><DeleteOutlined/> 删除作业</a-button></a-space>
              </section>
            </a-tab-pane>
            <a-tab-pane key="submission" :tab="role==='TEACHER'?'提交情况':'提交作业'">
              <template v-if="role==='TEACHER'">
                <section class="assignment-pane teacher-submission-pane">
                  <div class="assignment-pane-heading"><h2>提交概览</h2><a-button :href="`/api/v1/assignments/${selectedAssignment.id}/download.zip`" target="_blank"><DownloadOutlined/> 批量下载</a-button></div>
                  <div class="detail-metrics"><div><span>应提交</span><strong>{{teacherSubmissionSummary.total}}</strong></div><div><span>已提交</span><strong>{{teacherSubmissionSummary.submitted}}</strong></div><div><span>未提交</span><strong>{{teacherSubmissionSummary.pending}}</strong></div><div><span>迟交</span><strong>{{teacherSubmissionSummary.late}}</strong></div></div>
                </section>
                <section class="assignment-pane">
                  <div class="assignment-pane-heading"><h2>提交明细</h2></div>
                  <div class="board-toolbar"><a-input-search v-model:value="boardQuery" allow-clear placeholder="搜索姓名或学号"/><a-select v-model:value="boardTeamFilter" :options="boardTeamOptions"/><a-segmented v-model:value="boardFilter" :options="[{label:'全部',value:'ALL'},{label:'未提交',value:'NOT_SUBMITTED'},{label:'已提交',value:'SUBMITTED'},{label:'迟交',value:'LATE'}]"/></div>
                  <a-table :data-source="filteredBoard" row-key="id" size="small" :pagination="{pageSize:15}" :scroll="{x:760}"><a-table-column title="提交对象" data-index="owner"/><a-table-column v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" title="学号"><template #default="{record}">{{record.student_no||'-'}}</template></a-table-column><a-table-column title="小组"><template #default="{record}">{{record.team_name||'未分组'}}</template></a-table-column><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag><a-tag v-if="record.is_late" color="red">迟交</a-tag></template></a-table-column><a-table-column title="提交时间"><template #default="{record}">{{formatTime(record.submitted_at)}}</template></a-table-column><a-table-column title="操作" :width="100"><template #default="{record}"><a-button v-if="record.status==='SUBMITTED'" type="link" @click="openSubmissionDetail(record)"><EyeOutlined/> 查看</a-button><span v-else>-</span></template></a-table-column></a-table>
                </section>
              </template>
              <template v-else>
              <div class="submission-summary" :class="{submitted:assignmentSubmitted,closed:!canSubmitAssignment&&!assignmentSubmitted}"><span class="submission-summary-icon"><CheckCircleOutlined v-if="assignmentSubmitted"/><InboxOutlined v-else/></span><div><strong>{{assignmentSubmitted?'已提交':new Date(selectedAssignment.due_at)<=new Date()?'已截止':'待提交'}}</strong><span>{{assignmentSubmitted?`${formatTime(selectedAssignment.submission?.submitted_at)} · ${draftFiles.length} 个附件`:`截止 ${formatTime(selectedAssignment.due_at)}`}}</span></div></div>
              <section class="assignment-pane submission-files-pane">
                <div class="assignment-pane-heading"><h2>提交附件</h2><a-upload v-if="canSubmitAssignment" :custom-request="uploadFile" multiple><a-button><UploadOutlined/> 上传附件</a-button></a-upload></div>
                <a-empty v-if="!draftFiles.length" class="detail-empty" description="暂无提交附件"/>
                <div v-else class="assignment-file-list"><div v-for="file in draftFiles" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,draftFiles)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-tooltip v-if="canSubmitAssignment" :title="file.submitted?'从待更新附件中移除':'删除附件'"><a-button danger type="text" shape="circle" @click="deleteDraft(file)"><DeleteOutlined/></a-button></a-tooltip></div></div>
                <div v-if="canSubmitAssignment" class="submission-actions"><a-button type="primary" :disabled="!draftFiles.length" @click="submitAssignment">{{assignmentIsUpdate?'更新提交':'提交'}}</a-button></div>
              </section>
              </template>
            </a-tab-pane>
            <a-tab-pane v-if="role==='TEACHER'" key="reviews" tab="互评管理">
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>互评设置</h2><a-space wrap><a-tag v-if="selectedCampaign" :color="selectedCampaign.status==='CLOSED'?'default':'blue'">{{statusLabel(selectedCampaign.status)}}</a-tag><a-tag v-else-if="selectedAssignment.auto_review_enabled" color="blue">{{selectedAssignment.auto_review_status==='FAILED'?'创建失败':'等待创建'}}</a-tag><a-tag v-else>未启用</a-tag><a-button v-if="reviewConfigEditable" @click="openAssignmentEdit"><EditOutlined/> 编辑设置</a-button></a-space></div>
                <a-descriptions v-if="selectedAssignment.auto_review_enabled||selectedCampaign" bordered :column="2" size="small">
                  <a-descriptions-item label="分配模式">{{(selectedCampaign?.mode||selectedAssignment.auto_review_mode)==='CLASS'?'班级一人评一人':'组内一人评一人'}}</a-descriptions-item>
                  <a-descriptions-item label="互评截止">{{formatTime(selectedCampaign?.due_at||selectedAssignment.auto_review_due_at)}}</a-descriptions-item>
                  <a-descriptions-item label="创建方式">{{selectedCampaign?'已生成互评活动':'作业截止后自动创建'}}</a-descriptions-item>
                  <a-descriptions-item label="配置状态">{{selectedCampaign?'已创建':selectedAssignment.auto_review_status==='FAILED'?'失败':'待创建'}}</a-descriptions-item>
                </a-descriptions>
                <a-empty v-else class="detail-empty" description="本作业未启用互评"/>
                <a-alert v-if="selectedAssignment.auto_review_error" class="review-status-alert" type="error" show-icon message="互评活动创建失败" :description="selectedAssignment.auto_review_error"/>
                <a-alert v-else-if="selectedAssignment.auto_review_enabled&&!selectedCampaign" class="review-status-alert" type="info" show-icon message="互评将在作业截止后自动创建" description="系统会冻结届时的正式提交版本并按当前模式分配评价对象。"/>
              </section>
              <section v-if="selectedAssignment.auto_review_enabled||selectedCampaign" class="assignment-pane">
                <div class="assignment-pane-heading"><h2>互评标准</h2><a-upload v-if="reviewConfigEditable" :custom-request="uploadReviewCriteria" multiple accept=".md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.xlsx"><a-button><UploadOutlined/> 上传标准附件</a-button></a-upload></div>
                <p class="detail-description">{{selectedCampaign?.criteria_text||selectedAssignment.auto_review_criteria_text||'标准见附件'}}</p>
                <a-empty v-if="!reviewCriteriaFiles.length" class="detail-empty" description="暂无标准附件"/>
                <div v-else class="assignment-file-list"><div v-for="file in reviewCriteriaFiles" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,reviewCriteriaFiles)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-space><a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip><a-tooltip v-if="reviewConfigEditable" title="删除附件"><a-button danger type="text" shape="circle" @click="deleteDraft(file)"><DeleteOutlined/></a-button></a-tooltip></a-space></div></div>
              </section>
              <template v-if="selectedCampaign">
                <section class="assignment-pane">
                  <div class="assignment-pane-heading"><h2>完成情况</h2><a-button v-if="selectedCampaign.status==='ACTIVE'&&new Date(selectedCampaign.due_at)>new Date()" danger @click="closeCampaign">提前截止互评</a-button></div>
                  <div class="detail-metrics"><div><span>已分配</span><strong>{{campaignStats?.assigned_count??campaignStats?.reviewer_count??0}}</strong></div><div><span>已完成</span><strong>{{campaignStats?.completed_count??campaignStats?.review_count??0}}</strong></div><div><span>已跳过</span><strong>{{campaignStats?.skipped_count||0}}</strong></div><div><span>完成率</span><strong>{{campaignStats?.completion_rate??0}}%</strong></div></div>
                  <a-alert v-for="item in campaignStats?.skipped||[]" :key="item.reviewer_id" class="review-status-alert" type="warning" :message="`${item.reviewer_name}：${item.reason}`"/>
                </section>
                <section class="assignment-pane"><div class="assignment-pane-heading"><h2>评价明细</h2><span>{{campaignReviews.length}} 条评价</span></div><a-empty v-if="!campaignReviews.length" class="detail-empty" description="暂无已提交评价"/><a-table v-else :data-source="campaignReviews" row-key="id" size="small" :scroll="{x:720}"><a-table-column title="评价人" data-index="reviewer_name"/><a-table-column title="被评价人" data-index="reviewee_name"/><a-table-column title="得分" data-index="total_score"/><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="操作" width="72"><template #default="{record}"><a-tooltip v-if="record.status==='VALID'" title="作废评价"><a-button danger type="text" shape="circle" @click="openInvalidate(record)"><DeleteOutlined/></a-button></a-tooltip></template></a-table-column></a-table></section>
              </template>
            </a-tab-pane>
            <a-tab-pane v-if="role==='TEACHER'" key="grades" tab="成绩管理">
              <a-empty v-if="!selectedCampaign" class="detail-empty grade-empty" description="本作业没有互评活动，暂无成绩可管理"/>
              <a-result v-else-if="!selectedCampaign.grades_generated_at||!gradeDetail" status="info" title="成绩尚未生成" sub-title="互评截止后系统会生成成绩草稿，届时可填写小组系数并发布。"/>
              <template v-else>
                <section class="assignment-pane grade-management-heading"><div class="assignment-pane-heading"><h2>成绩概览</h2><a-button type="primary" :disabled="!gradeDetail.summary.publishable" @click="openGradePublish"><CheckCircleOutlined/> 发布成绩</a-button></div><div class="grade-summary"><div><span>参与学生</span><strong>{{gradeDetail.total}}</strong></div><div><span>可发布</span><strong>{{gradeDetail.summary.publishable}}</strong></div><div><span>待处理</span><strong>{{gradeDetail.summary.pending}}</strong></div><div><span>已发布</span><strong>{{gradeDetail.summary.published}}</strong></div></div></section>
                <section class="assignment-pane grade-section"><div class="assignment-pane-heading"><h2>小组系数</h2><span>每组统一设置，保存后生成草稿最终分</span></div><a-empty v-if="!gradeDetail.groups.length" description="暂无可设置系数的小组"/><a-table v-else :data-source="gradeDetail.groups" row-key="team_id" size="small" :pagination="false" :scroll="{x:620}"><a-table-column title="小组" data-index="team_name"/><a-table-column title="人数" data-index="member_count"/><a-table-column title="已发布系数"><template #default="{record}">{{record.published_value??'-'}}</template></a-table-column><a-table-column title="草稿系数"><template #default="{record}"><a-input-number v-model:value="record.input_value" :min="0" :precision="2" placeholder="请输入"/></template></a-table-column><a-table-column title="操作" width="90"><template #default="{record}"><a-button type="link" @click="saveCoefficient(record)">保存</a-button></template></a-table-column></a-table></section>
                <section class="assignment-pane grade-section"><div class="assignment-pane-heading"><h2>个人成绩明细</h2><span>最终分最高为 100 分</span></div><a-table :data-source="gradeDetail.items" row-key="id" :scroll="{x:980}"><a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="student_name"/><a-table-column title="小组" data-index="team_name"/><a-table-column title="互评分"><template #default="{record}">{{record.peer_score??'-'}}</template></a-table-column><a-table-column title="小组系数"><template #default="{record}">{{record.draft_coefficient??'-'}}</template></a-table-column><a-table-column title="草稿最终分"><template #default="{record}">{{record.draft_score??'-'}}</template></a-table-column><a-table-column title="已发布最终分"><template #default="{record}">{{record.score??'-'}}</template></a-table-column><a-table-column title="状态"><template #default="{record}"><a-tag :color="record.status==='PUBLISHED'?'green':record.status==='CHANGED'?'orange':'default'">{{statusLabel(record.status)}}</a-tag></template></a-table-column><a-table-column title="记录" width="72"><template #default="{record}"><a-tooltip title="查看修订记录"><a-button type="text" shape="circle" @click="openGradeRevisions({...record,assignment_title:gradeDetail.assignment.title})"><FileTextOutlined/></a-button></a-tooltip></template></a-table-column></a-table></section>
              </template>
            </a-tab-pane>
          </a-tabs>
        </section>
      </template>

      <template v-else-if="view==='reviews'">
        <div class="page-title"><div><div class="eyebrow">组内作品互评</div><h1>作品互评</h1><p>查看分配给你的作品，在截止前提交或更新评价。</p></div></div>
        <a-empty v-if="!campaigns.length" description="暂无互评活动"/><a-card v-for="item in campaigns" :key="item.id" class="assignment-row" :class="campaignStateClass(item)" :bordered="false" @click="openCampaign(item)"><div class="assignment-icon cyan"><FormOutlined/></div><div class="assignment-main"><div class="assignment-heading"><h3>{{item.assignment_title}}</h3><a-tag v-if="['COMPLETED','SKIPPED'].includes(item.allocation_status)">已完成</a-tag><a-tag v-else-if="new Date(item.due_at)<=new Date()" color="error">已逾期</a-tag></div><p>{{item.criteria_text||'互评标准见附件'}}</p><div class="assignment-meta"><span>{{item.mode==='CLASS'?'班级一人评一人':'组内一人评一人'}}</span><span>截止 {{formatTime(item.due_at)}}</span></div></div><div class="assignment-end"><strong>{{new Date(item.due_at)<=new Date()?'查看结果':item.allocation_status==='COMPLETED'?'可更新':'待评价'}}</strong></div></a-card>
      </template>

      <template v-else-if="view==='review-detail'&&selectedCampaign">
        <div class="page-title detail-title"><div><div class="eyebrow">互评详情</div><h1>{{selectedCampaign.assignment_title}}</h1><div class="assignment-title-meta"><a-tag color="cyan">{{selectedCampaign.mode==='CLASS'?'班级一人评一人':'组内一人评一人'}}</a-tag><a-tag :color="campaignEnded?'default':reviewTask?.status==='COMPLETED'?'green':'blue'">{{campaignEnded?'已结束':reviewTask?.status==='COMPLETED'?'已完成':'进行中'}}</a-tag><span>截止 {{formatTime(selectedCampaign.due_at)}}</span></div></div><a-button @click="router.push('/reviews')"><ArrowLeftOutlined/> 返回互评列表</a-button></div>
        <section class="assignment-workspace review-workspace">
          <template v-if="campaignEnded">
            <section class="assignment-pane"><div class="submission-summary submitted"><span class="submission-summary-icon"><CheckCircleOutlined/></span><div><strong>本次互评已结束</strong><span>已提交的评价和收到的反馈均已保留</span></div></div></section>
            <section class="assignment-pane"><div class="assignment-pane-heading"><h2>收到的评价</h2><span>{{currentCampaignReviews.length}} 条评价</span></div><a-empty v-if="!currentCampaignReviews.length" class="detail-empty" description="暂无收到的有效评价"/><div v-for="item in currentCampaignReviews" :key="item.id" class="review-result"><div><span>评价人</span><strong>{{item.reviewer_name}}</strong></div><div class="review-result-score"><strong>{{item.total_score}}</strong><span>分</span></div><p>{{item.comment}}</p></div></section>
          </template>
          <template v-else>
            <a-alert v-if="reviewTask?.status==='SKIPPED'" type="warning" show-icon message="本次任务已跳过" :description="reviewTask.skip_reason"/>
            <template v-else-if="reviewTask">
              <section class="assignment-pane"><div class="assignment-pane-heading"><h2>评价对象</h2><span>提交于 {{formatTime(reviewTask.submission?.submitted_at)}}</span></div><div class="review-subject"><span class="review-subject-icon"><UserOutlined/></span><div><strong>{{reviewTask.reviewee?.name}}</strong><span>{{reviewTask.reviewee?.student_no}}</span></div></div></section>
              <section class="assignment-pane"><div class="assignment-pane-heading"><h2>互评标准</h2><span v-if="reviewTask.campaign.criteria_files.length">{{reviewTask.campaign.criteria_files.length}} 个附件</span></div><p class="detail-description review-criteria">{{reviewTask.campaign.criteria_text||'互评标准见附件'}}</p><div v-if="reviewTask.campaign.criteria_files.length" class="assignment-file-list"><div v-for="file in reviewTask.campaign.criteria_files" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,reviewTask.campaign.criteria_files)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip></div></div></section>
              <section class="assignment-pane"><div class="assignment-pane-heading"><h2>作品文件</h2><span>{{reviewTask.submission?.files?.length||0}} 个附件</span></div><a-empty v-if="!reviewTask.submission?.files?.length" class="detail-empty" description="暂无作品文件"/><div v-else class="assignment-file-list"><div v-for="file in reviewTask.submission.files" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,reviewTask.submission.files)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip></div></div></section>
              <section class="assignment-pane review-response-pane"><div class="assignment-pane-heading"><h2>{{reviewTask.status==='COMPLETED'?'更新评价':'提交评价'}}</h2><a-tag v-if="reviewTask.status==='COMPLETED'" color="green">已提交，可在截止前修改</a-tag></div><a-form class="review-form" layout="vertical"><a-form-item label="总分" required><div class="score-control"><a-slider v-model:value="reviewForm.score" :min="0" :max="100"/><a-input-number v-model:value="reviewForm.score" :min="0" :max="100"/></div></a-form-item><a-form-item label="评语" required><a-textarea v-model:value="reviewForm.comment" :rows="5" :maxlength="2000" show-count/></a-form-item><div class="submission-actions"><a-button type="primary" @click="submitReview">{{reviewTask.status==='COMPLETED'?'更新评价':'提交评价'}}</a-button></div></a-form></section>
            </template>
          </template>
        </section>
      </template>

      <template v-else-if="view==='grades'">
        <div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'数据归档':'学习成果'}}</div><h1>{{role==='TEACHER'?'成绩与导出':'成绩与反馈'}}</h1><p>{{role==='TEACHER'?'集中导出当前教学班的成员、小组、互评和成绩数据。':'查看已发布的互评分、系数和最终成绩。'}}</p></div></div>
        <template v-if="role==='TEACHER'">
          <div class="export-grid">
            <section class="export-item"><div class="export-item-icon blue"><UserOutlined/></div><div><h2>成员名单</h2><p>导出学号、姓名、状态和所属小组。</p></div><a-space><a-button @click="downloadExport('members')"><DownloadOutlined/> XLSX</a-button><a-button @click="downloadExport('members','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
            <section class="export-item"><div class="export-item-icon purple"><TeamOutlined/></div><div><h2>小组名单</h2><p>导出小组、组长、人数、选题和状态。</p></div><a-space><a-button @click="downloadExport('teams')"><DownloadOutlined/> XLSX</a-button><a-button @click="downloadExport('teams','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
            <section class="export-item"><div class="export-item-icon cyan"><FormOutlined/></div><div><h2>互评记录</h2><p>导出评价人、被评价人、得分、状态和评语。</p></div><a-space><a-button @click="downloadExport('reviews')"><DownloadOutlined/> XLSX</a-button><a-button @click="downloadExport('reviews','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
            <section class="export-item export-grade-item"><div class="export-item-icon green"><TrophyOutlined/></div><div><h2>作业成绩</h2><p>选择一项已生成成绩记录的互评作业。</p><a-select v-model:value="selectedGradeAssignmentId" allow-clear placeholder="选择作业" :options="gradeAssignments.map(item=>({value:item.id,label:item.title}))"/></div><a-space><a-button :disabled="!selectedGradeAssignmentId" @click="downloadExport('grades')"><DownloadOutlined/> XLSX</a-button><a-button :disabled="!selectedGradeAssignmentId" @click="downloadExport('grades','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
          </div>
        </template>
        <template v-else><a-empty v-if="!grades.length" description="暂无已发布成绩"/><a-table v-else :data-source="grades" row-key="id" :scroll="{x:720}"><a-table-column title="作业" data-index="assignment_title"/><a-table-column title="互评分" data-index="peer_score"/><a-table-column title="小组系数" data-index="coefficient"/><a-table-column title="最终分" data-index="score"/><a-table-column title="状态"><template #default="{record}"><a-tag color="green">{{statusLabel(record.status)}}</a-tag></template></a-table-column></a-table></template>
      </template>
      <template v-else-if="view==='system'&&role==='TEACHER'"><div class="page-title"><div><div class="eyebrow">运行管理</div><h1>系统与审计</h1><p>关键业务操作不可修改。</p></div></div><a-empty v-if="!audits.length" description="暂无审计记录"/><a-table v-else :data-source="audits" row-key="id"><a-table-column title="时间"><template #default="{record}">{{formatTime(record.created_at)}}</template></a-table-column><a-table-column title="操作者" data-index="actor"/><a-table-column title="操作"><template #default="{record}">{{actionLabel(record.action)}}</template></a-table-column><a-table-column title="对象"><template #default="{record}">{{objectLabel(record.object_type)}}</template></a-table-column></a-table></template>
    </a-spin></div></a-layout-content>

    <a-drawer :open="filePreview.open" :width="'min(100vw, 1040px)'" placement="right" root-class-name="file-preview-drawer" :title="activePreviewFile?.name||'文件预览'" @close="closeFilePreview">
      <div class="file-preview-toolbar">
        <a-space>
          <a-tooltip title="上一个文件"><span><a-button shape="circle" :disabled="filePreview.index<=0" @click="switchFilePreview(-1)"><LeftOutlined/></a-button></span></a-tooltip>
          <span>{{filePreview.files.length ? `${filePreview.index+1} / ${filePreview.files.length}` : '0 / 0'}}</span>
          <a-tooltip title="下一个文件"><span><a-button shape="circle" :disabled="filePreview.index>=filePreview.files.length-1" @click="switchFilePreview(1)"><RightOutlined/></a-button></span></a-tooltip>
        </a-space>
        <a-button v-if="activePreviewFile" :href="`/api/v1/files/${activePreviewFile.id}`"><DownloadOutlined/> 下载原文件</a-button>
      </div>
      <div class="file-preview-stage">
        <a-spin v-if="filePreview.loading" size="large" tip="正在加载文件"/>
        <a-result v-else-if="filePreview.error" status="warning" title="无法在线预览" :sub-title="filePreview.error"><template #extra><a-button v-if="activePreviewFile" type="primary" :href="`/api/v1/files/${activePreviewFile.id}`"><DownloadOutlined/> 下载原文件</a-button></template></a-result>
        <img v-else-if="filePreview.url&&activePreviewIsImage" :src="filePreview.url" :alt="activePreviewFile?.name" @error="filePreview.error='图片加载失败，请下载原文件查看。'"/>
        <iframe v-else-if="filePreview.url" :src="filePreview.url" :title="activePreviewFile?.name"/>
      </div>
    </a-drawer>

    <a-modal v-model:open="noticesOpen" title="站内通知" :footer="null" width="520px" centered><div class="notification-toolbar"><span>{{notifications.filter(x=>!x.read).length ? `${notifications.filter(x=>!x.read).length} 条未读消息` : '消息已全部阅读'}}</span><a-button v-if="notifications.some(x=>!x.read)" type="link" @click="readAll">全部标为已读</a-button></div><a-empty v-if="!notifications.length" description="暂无通知"/><div v-else class="notification-list"><div v-for="item in notifications" :key="item.id" class="notification-item" :class="{unread:!item.read}"><span class="notification-dot"/><div><strong>{{item.title}}</strong><span>{{formatTime(item.created_at)}}</span></div></div></div></a-modal>

    <a-modal v-model:open="modals.class" :title="classForm.id?'编辑教学班':'创建教学班'" ok-text="保存" @ok="saveClass"><a-form layout="vertical"><a-form-item label="课程"><a-input value="软件工程" disabled/></a-form-item><a-form-item label="学期" required><a-input v-model:value="classForm.semester" placeholder="例如：2026 秋季"/></a-form-item><a-form-item label="班级名称" required><a-input v-model:value="classForm.name"/></a-form-item><a-form-item label="组队截止时间"><a-input v-model:value="classForm.team_deadline" type="datetime-local"/></a-form-item><a-form-item label="小组人数上限"><a-input-number v-model:value="classForm.max_team_members" :min="2" :max="20"/></a-form-item><a-form-item label="选题可见性"><a-switch v-model:checked="classForm.topic_public" checked-children="公开" un-checked-children="仅本组"/></a-form-item><a-form-item label="邀请码加入"><a-switch v-model:checked="classForm.invite_requires_approval" checked-children="需审核" un-checked-children="自动加入"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.joinClass" title="通过邀请码加入教学班" ok-text="提交申请" @ok="joinClass"><a-form layout="vertical"><a-form-item label="邀请码" required><a-input v-model:value="joinClassForm.invite_code" maxlength="12" placeholder="请输入教师提供的邀请码"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.import" title="导入学生名单" :footer="null" @cancel="closeImport"><a-steps :current="importState.step" size="small" :items="[{title:'上传名单'},{title:'预览校验'},{title:'确认导入'}]"/><a-upload-dragger v-if="!importState.result" :before-upload="chooseRoster" :show-upload-list="true" :max-count="1" accept=".csv,.xlsx"><p class="ant-upload-drag-icon"><UploadOutlined/></p><p>选择 XLSX 或 CSV 名单</p><p class="ant-upload-hint">必填列：学号、姓名</p></a-upload-dragger><a-table v-if="importState.preview" :data-source="importState.preview.rows" size="small" row-key="row" :pagination="{pageSize:5}"><a-table-column title="行" data-index="row"/><a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="name"/><a-table-column title="结果" data-index="reason"/></a-table><a-result v-if="importState.result" status="success" title="名单导入完成" :sub-title="`新建 ${importState.result.created} 个账号，加入 ${importState.result.joined} 名学生，跳过 ${importState.result.skipped} 行`"/><div class="modal-actions"><a-button @click="closeImport">{{importState.result?'关闭':'取消'}}</a-button><a-button v-if="!importState.preview" type="primary" :loading="importState.loading" @click="previewRoster">校验名单</a-button><a-button v-else-if="!importState.result" type="primary" :loading="importState.loading" @click="confirmRoster">确认导入</a-button><a-button v-else :href="`/api/v1/classes/${classId}/members/import/${importState.preview.batch_id}/result.csv`"><DownloadOutlined/> 下载结果</a-button></div></a-modal>
    <a-modal v-model:open="modals.member" :title="memberForm.id?'编辑成员':'添加成员'" :confirm-loading="memberSaving" ok-text="保存" @ok="saveMember"><a-form layout="vertical"><a-form-item label="学号" required><a-input v-model:value="memberForm.student_no" :disabled="Boolean(memberForm.id)" maxlength="32"/></a-form-item><a-form-item label="姓名" required><a-input v-model:value="memberForm.name" maxlength="80"/></a-form-item></a-form></a-modal>
    <a-modal :open="Boolean(memberDetail)" title="成员信息" :footer="null" @cancel="memberDetail=null"><a-descriptions v-if="memberDetail" bordered :column="1"><a-descriptions-item label="学号">{{memberDetail.student_no}}</a-descriptions-item><a-descriptions-item label="姓名">{{memberDetail.name}}</a-descriptions-item><a-descriptions-item label="小组">{{memberDetail.team||'未入组'}}</a-descriptions-item><a-descriptions-item label="加入时间">{{formatTime(memberDetail.joined_at)}}</a-descriptions-item></a-descriptions></a-modal>
    <a-modal v-model:open="modals.team" title="创建小组" @ok="createTeam"><a-form layout="vertical"><a-form-item label="小组名称" required><a-input v-model:value="teamForm.name"/></a-form-item><a-checkbox v-model:checked="teamForm.open_recruitment">允许其他成员申请加入</a-checkbox></a-form></a-modal>
    <a-modal v-model:open="selectedTeam" :title="selectedTeam?.name" :footer="null"><template v-if="selectedTeam"><p>组长：{{selectedTeam.leader_name}} · {{selectedTeam.member_count}} / {{selectedTeam.max_members}} 人</p><a-list :data-source="selectedTeam.members||[]"><template #renderItem="{item}"><a-list-item>{{item.name}}（{{item.student_no}}）<a-space><a-tag>{{roleLabel(item.role)}}</a-tag><a-button v-if="selectedTeam.is_leader&&item.role!=='LEADER'" type="link" @click="transferLeader(item.id)">移交组长</a-button></a-space></a-list-item></template></a-list><template v-if="selectedTeam.is_leader"><a-divider/><a-space-compact block><a-select v-model:value="inviteTarget" placeholder="选择未入组学生" style="width:100%" :options="members.filter(x=>!x.team).map(x=>({value:x.id,label:`${x.name}（${x.student_no}）`}))"/><a-button type="primary" :disabled="!inviteTarget" @click="inviteMember">邀请</a-button></a-space-compact><a-divider/><a-form layout="vertical"><a-form-item label="选题名称"><a-input v-model:value="topicForm.name"/></a-form-item><a-form-item label="选题说明"><a-textarea v-model:value="topicForm.description" :rows="3"/></a-form-item><a-space><a-button type="primary" @click="saveTopic">提交选题审核</a-button><a-button danger @click="disbandTeam">解散小组</a-button></a-space></a-form></template><a-button v-else-if="role==='STUDENT'&&selectedTeam.id===session.context?.team_membership?.team_id" danger @click="leaveTeam">退出小组</a-button></template></a-modal>
    <a-modal v-model:open="modals.assignment" :title="assignmentForm.id ? '编辑作业' : '新建作业'" :footer="null" width="720px">
      <a-form layout="vertical">
        <a-form-item v-if="!assignmentForm.id" label="教学班" required><a-select v-model:value="assignmentForm.class_ids" mode="multiple" placeholder="选择一个或多个教学班" :options="classOptions"/></a-form-item>
        <a-form-item label="标题" required><a-input v-model:value="assignmentForm.title"/></a-form-item>
        <a-form-item label="提交类型" :help="assignmentForm.has_submissions ? '已有提交，不能修改提交类型' : ''"><a-segmented v-model:value="assignmentForm.submitter_type" :disabled="assignmentForm.has_submissions||assignmentForm.auto_review_enabled" :options="[{label:'个人作业',value:'INDIVIDUAL'},{label:'小组作业',value:'TEAM'}]"/></a-form-item>
        <a-form-item label="开始时间"><a-input v-model:value="assignmentForm.starts_at" type="datetime-local"/></a-form-item>
        <a-form-item label="截止时间" required><a-input v-model:value="assignmentForm.due_at" type="datetime-local"/></a-form-item>
        <a-form-item label="说明" required><div class="editor-shell"><div v-if="descriptionEditor" class="editor-toolbar"><a-tooltip title="二级标题"><a-button size="small" :type="descriptionEditor.isActive('heading',{level:2})?'primary':'default'" @click="descriptionEditor.chain().focus().toggleHeading({level:2}).run()">H2</a-button></a-tooltip><a-tooltip title="粗体"><a-button size="small" :type="descriptionEditor.isActive('bold')?'primary':'default'" @click="descriptionEditor.chain().focus().toggleBold().run()"><BoldOutlined/></a-button></a-tooltip><a-tooltip title="无序列表"><a-button size="small" @click="descriptionEditor.chain().focus().toggleBulletList().run()"><UnorderedListOutlined/></a-button></a-tooltip><a-tooltip title="有序列表"><a-button size="small" @click="descriptionEditor.chain().focus().toggleOrderedList().run()"><OrderedListOutlined/></a-button></a-tooltip><a-tooltip title="链接"><a-button size="small" @click="setDescriptionLink"><LinkOutlined/></a-button></a-tooltip><a-tooltip title="代码块"><a-button size="small" @click="descriptionEditor.chain().focus().toggleCodeBlock().run()"><CodeOutlined/></a-button></a-tooltip></div><EditorContent :editor="descriptionEditor"/></div></a-form-item>
        <a-form-item v-if="!assignmentForm.id" label="作业附件"><a-upload :before-upload="queueAssignmentAttachment" :show-upload-list="false" multiple accept=".md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.pptx,.xlsx,.zip,.rar,.7z"><a-button><UploadOutlined/> 选择附件</a-button></a-upload><div v-for="(file,index) in pendingAssignmentFiles" :key="file.uid||`${file.name}-${index}`" class="uploaded-file"><span>{{file.name}}</span><a-button danger type="link" @click="removePendingAssignmentAttachment(index)">移除</a-button></div></a-form-item>
        <a-divider orientation="left">互评设置</a-divider>
        <a-alert v-if="assignmentForm.id&&!reviewConfigEditable" type="info" show-icon message="互评配置已锁定" description="作业截止、提前关闭或互评活动创建后不能再修改。"/>
        <a-form-item label="启用互评"><a-switch v-model:checked="assignmentForm.auto_review_enabled" :disabled="Boolean(assignmentForm.id)&&!reviewConfigEditable" @change="toggleAutoReview"/></a-form-item>
        <template v-if="assignmentForm.auto_review_enabled">
          <a-form-item label="互评模式" required><a-segmented v-model:value="assignmentForm.auto_review_mode" :disabled="Boolean(assignmentForm.id)&&!reviewConfigEditable" :options="[{label:'组内一人评一人',value:'TEAM'},{label:'班级一人评一人',value:'CLASS'}]"/></a-form-item>
          <a-form-item label="互评标准"><a-textarea v-model:value="assignmentForm.auto_review_criteria_text" :disabled="Boolean(assignmentForm.id)&&!reviewConfigEditable" :rows="4" maxlength="5000" show-count/></a-form-item>
          <a-form-item label="互评标准附件"><a-upload v-if="!assignmentForm.id||reviewConfigEditable" :before-upload="queueAutoReviewAttachment" :show-upload-list="false" multiple accept=".md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.xlsx"><a-button><UploadOutlined/> 选择附件</a-button></a-upload><div v-if="assignmentForm.id" v-for="file in reviewCriteriaFiles" :key="file.id" class="uploaded-file"><span>{{file.name}}</span><a-button v-if="reviewConfigEditable" danger type="link" @click="deleteDraft(file)">移除</a-button></div><div v-for="(file,index) in pendingAutoReviewFiles" :key="file.uid||`${file.name}-${index}`" class="uploaded-file"><span>{{file.name}}</span><a-button danger type="link" @click="pendingAutoReviewFiles.splice(index,1)">移除</a-button></div></a-form-item>
          <a-form-item label="互评截止时间" required><a-input v-model:value="assignmentForm.auto_review_due_at" :disabled="Boolean(assignmentForm.id)&&!reviewConfigEditable" type="datetime-local"/></a-form-item>
        </template>
        <a-checkbox v-model:checked="assignmentForm.allow_late">允许迟交并标记</a-checkbox>
        <div class="modal-actions"><a-button @click="modals.assignment=false">取消</a-button><a-button v-if="!assignmentForm.id" @click="createAssignment(false)">保存草稿</a-button><a-button type="primary" @click="assignmentForm.id?createAssignment():createAssignment(true)">{{assignmentForm.id?'保存修改':'发布'}}</a-button></div>
      </a-form>
    </a-modal>
    <a-modal v-model:open="selectedSubmission" :title="selectedSubmission?`${selectedSubmission.owner} · 提交详情`:'提交详情'" :footer="null" width="680px"><template v-if="selectedSubmission"><a-descriptions bordered :column="2" size="small"><a-descriptions-item v-if="selectedSubmission.student_no" label="学号">{{selectedSubmission.student_no}}</a-descriptions-item><a-descriptions-item label="小组">{{selectedSubmission.team_name||'未分组'}}</a-descriptions-item><a-descriptions-item label="提交时间">{{formatTime(selectedSubmission.submitted_at)}}</a-descriptions-item><a-descriptions-item label="状态"><a-tag>{{statusLabel(selectedSubmission.status)}}</a-tag><a-tag v-if="selectedSubmission.is_late" color="red">迟交</a-tag></a-descriptions-item></a-descriptions><div class="submission-detail-heading"><h3>提交附件</h3><span>{{selectedSubmission.files?.length||0}} 个附件</span></div><a-empty v-if="!selectedSubmission.files?.length" class="detail-empty" description="暂无提交附件"/><div v-else class="assignment-file-list"><div v-for="file in selectedSubmission.files" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,selectedSubmission.files)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip></div></div></template></a-modal>
    <a-modal v-model:open="selectedGrade" :title="selectedGrade ? `${selectedGrade.assignment_title} · 修订记录` : '修订记录'" :footer="null"><a-empty v-if="!gradeRevisions.length" description="暂无修订记录"/><a-timeline v-else><a-timeline-item v-for="item in gradeRevisions" :key="item.id"><strong>{{item.peer_score}} × {{item.coefficient}} = {{item.score}} 分</strong><p>{{item.reason||'未填写修改原因'}}</p><span>{{formatTime(item.created_at)}}</span></a-timeline-item></a-timeline></a-modal>
    <a-modal v-model:open="modals.gradePublish" title="确认发布成绩" ok-text="确认发布" @ok="publishGrades"><a-alert type="info" show-icon :message="`可发布 ${gradeDetail?.summary.publishable||0} 人，待处理 ${gradeDetail?.summary.pending||0} 人`" :description="gradeDetail?.summary.changed?`其中 ${gradeDetail.summary.changed} 人将更新已发布成绩。未获有效互评的学生不会发布。`:'发布后学生即可查看互评分、系数和最终分。'"/><a-form v-if="gradeDetail?.summary.changed" layout="vertical" class="grade-publish-form"><a-form-item label="修改原因" required><a-input v-model:value="gradePublishReason" maxlength="500" placeholder="请说明修改原因"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.topicDecision" title="驳回选题" ok-text="确认驳回" @ok="rejectTopic"><a-form layout="vertical"><a-form-item label="驳回原因" required><a-textarea v-model:value="topicDecisionForm.reason" :rows="3" placeholder="请说明需要修改的内容"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.invalidate" title="作废评价" @ok="invalidateReview"><a-form layout="vertical"><a-form-item label="原因" required><a-textarea v-model:value="invalidReason" :rows="3"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.password" title="修改密码" @ok="changePassword"><a-form layout="vertical"><a-form-item label="当前密码"><a-input-password v-model:value="passwordForm.current_password"/></a-form-item><a-form-item label="新密码"><a-input-password v-model:value="passwordForm.new_password"/></a-form-item></a-form></a-modal>
  </a-layout>
</template>
