<script setup>
import { computed, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { ArrowLeftOutlined, BoldOutlined, BookOutlined, CheckCircleOutlined, CodeOutlined, DashboardOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, EyeOutlined, FileTextOutlined, FormOutlined, InboxOutlined, LinkOutlined, OrderedListOutlined, QuestionCircleOutlined, RightOutlined, SettingOutlined, TeamOutlined, TrophyOutlined, UnorderedListOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { api, apiClientId } from '../api'
import FileReviewDrawer from '../components/FileReviewDrawer.vue'
import AssignmentMaterials from '../components/AssignmentMaterials.vue'
import ShellHeader from '../components/ShellHeader.vue'
import StudentPortfolioDrawer from '../components/StudentPortfolioDrawer.vue'
import AssignmentsPage from './shell/AssignmentsPage.vue'
import ClassesPage from './shell/ClassesPage.vue'
import GradesPage from './shell/GradesPage.vue'
import OverviewPage from './shell/OverviewPage.vue'
import ReviewDetailPage from './shell/ReviewDetailPage.vue'
import ReviewsPage from './shell/ReviewsPage.vue'
import SystemPage from './shell/SystemPage.vue'
import TeamsPage from './shell/TeamsPage.vue'
import TeamAssignmentChart from '../components/TeamAssignmentChart.vue'
import { useSessionStore } from '../stores/session'
import { shellContextKey } from '../shellContext'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const loadedViewKeys = reactive(new Set())
let loadGeneration = 0
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
const notifications = ref([])
const audits = ref([])
const auditSearch = ref('')
const auditSemester = ref('ALL')
const auditClassId = ref('ALL')
const auditActorRole = ref('ALL')
const auditPage = ref(1)
const auditPageSize = 10
const auditTotal = ref(0)
const selectedTeam = ref(null)
const selectedTeamAssignments = ref([])
const teamDrawerLoading = ref(false)
const exportingTeamIds = reactive(new Set())
let teamRequestGeneration = 0
const selectedAssignment = ref(null)
const selectedSubmission = ref(null)
const openedSubmissionPreview = ref('')
const fileReviewDrawer = ref(null)
const selectedCampaign = ref(null)
const reviewTask = ref(null)
const assignmentAttachments = ref([])
const reviewCriteriaFiles = ref([])
const pendingAssignmentFiles = ref([])
const draftFiles = ref([])
const boardFilter = ref('ALL')
const boardQuery = ref('')
const boardTeamFilter = ref('ALL')
const assignmentDetailTab = ref('details')
const noticesOpen = ref(false)
const modals = reactive({ class: false, import: false, member: false, team: false, assignment: false, password: false, topicDecision: false })
const classForm = reactive({ id: '', version: 1, semester: '', name: '', team_deadline: '', topic_public: false })
const memberForm = reactive({ id: '', student_no: '', name: '' })
const teamForm = reactive({ name: '', open_recruitment: true })
const assignmentForm = reactive({ id: '', version: 1, has_submissions: false, class_ids: [], title: '', description: '', submitter_type: 'INDIVIDUAL', starts_at: '', due_at: '', allow_late: false, publish: true, auto_review_enabled: false, auto_review_mode: 'TEAM', auto_review_criteria_text: '', auto_review_due_at: '' })
const reviewForm = reactive({ grade: 'A', comment: '', reviewee_id: '' })
const topicForm = reactive({ name: '', description: '' })
const topicDecisionForm = reactive({ id: '', reason: '' })
const passwordForm = reactive({ current_password: '', new_password: '' })
const inviteTarget = ref('')
const importState = reactive({ file: null, preview: null, result: null, step: 0, loading: false })
const filePreview = reactive({ open: false, files: [], index: 0, mode: 'PREVIEW', targets: [], targetIndex: 0, initialFeedback: null, pendingOnly: false, readonly: false, assignmentTitle: '' })
const currentTime = ref(Date.now())
let gateTimer
let clockTimer
let realtimeSource
let realtimeTimer
let safetyTimer
let realtimeDirty = false
const pendingRealtimeScopes = new Set()

const descriptionEditor = useEditor({
  content: '',
  extensions: [StarterKit.configure({ link: { openOnClick: false } })],
  onUpdate: ({ editor }) => { assignmentForm.description = editor.getHTML() }
})

const role = computed(() => session.user?.role)
const classId = computed(() => session.classId)
const view = computed(() => route.name === 'assignment-detail' ? 'assignment-detail' : route.name === 'review-detail' ? 'review-detail' : route.name === 'grade-detail' ? 'grade-detail' : route.params.view || 'overview')
const detailId = computed(() => route.params.id)
const pageKey = computed(() => `${role.value || 'guest'}:${classId.value || 'none'}:${view.value}:${detailId.value || ''}`)
const surfaceKey = computed(() => role.value === 'TEACHER' && view.value === 'assignment-detail'
  ? `${role.value}:${classId.value || 'none'}:assignments:`
  : pageKey.value)
const initialLoading = computed(() => loading.value && !loadedViewKeys.has(pageKey.value))
const navView = computed(() => view.value === 'assignment-detail' ? 'assignments' : view.value === 'review-detail' ? 'reviews' : view.value === 'grade-detail' ? 'grades' : view.value)
const activeClasses = computed(() => session.classes.filter(item => item.status === 'ACTIVE'))
const classOptions = computed(() => activeClasses.value.map(item => ({ value: item.id, label: `${item.semester} · ${item.name}` })))
const auditSemesterOptions = computed(() => [...new Set(session.classes.map(item => item.semester))].sort().map(value => ({ value, label: value })))
const auditClassOptions = computed(() => session.classes.filter(item => auditSemester.value === 'ALL' || item.semester === auditSemester.value).map(item => ({ value: item.id, label: item.name })))
const currentTeam = computed(() => teams.value.find(item => item.id === session.context?.team_membership?.team_id))
const needsTopicSubmission = computed(() => Boolean(currentTeam.value?.is_leader && !currentTeam.value.topic))
const ungroupedMembers = computed(() => members.value.filter(item => !item.team))
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
const groupedBoard = computed(() => {
  const groups = new Map()
  for (const item of filteredBoard.value) {
    const key = item.team_id || 'UNGROUPED'
    if (!groups.has(key)) groups.set(key, { id: key, name: item.team_name || '未分组', items: [] })
    groups.get(key).items.push(item)
  }
  return [...groups.values()].sort((a, b) => {
    if (a.id === 'UNGROUPED') return 1
    if (b.id === 'UNGROUPED') return -1
    return a.name.localeCompare(b.name, 'zh-CN', { numeric: true })
  })
})
const studentGradeSummary = computed(() => {
  return { count: grades.value.length, average: grades.value[0]?.final_grade || '-' }
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
const canManageTeamSubmission = computed(() => selectedAssignment.value?.submitter_type !== 'TEAM' || session.context?.team_membership?.role === 'LEADER')
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
  if (!canManageTeamSubmission.value) return false
  return new Date(assignment.due_at) > new Date() || (!assignmentSubmitted.value && assignment.allow_late)
})
const selectedReviewCandidate = computed(() => reviewTask.value?.candidates?.find(item => item.user_id === reviewForm.reviewee_id) || null)
const reviewConfigEditable = computed(() => Boolean(selectedAssignment.value && selectedAssignment.value.status !== 'CLOSED' && new Date(selectedAssignment.value.due_at) > new Date() && !selectedCampaign.value))
const studentLatestGrade = computed(() => grades.value[0])
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
const menu = computed(() => {
  if (role.value === 'TEACHER') return [
    ['overview', DashboardOutlined, '总览'], ['classes', BookOutlined, '教学班'], ['teams', TeamOutlined, '小组与选题'],
    ['assignments', FileTextOutlined, '作业管理'], ['grades', TrophyOutlined, '成绩与导出'], ['system', SettingOutlined, '系统与审计']
  ]
  if (session.teamGate) return [['teams', TeamOutlined, '加入小组']]
  return [['overview', DashboardOutlined, '总览'], ['teams', TeamOutlined, '我的小组'], ['assignments', FileTextOutlined, '我的作业'], ['reviews', FormOutlined, '作品互评'], ['grades', TrophyOutlined, '成绩与反馈']]
})

function iso(value) { return value ? new Date(value).toISOString() : null }
function idempotencyKey() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('')
}
function localDateTime(value) { if (!value) return ''; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-' }
function assignmentCountdown(item) {
  const start = item.starts_at ? new Date(item.starts_at).getTime() : 0
  const due = new Date(item.due_at).getTime()
  if (item.status === 'CLOSED' || due <= currentTime.value) return { label: '已结束', state: 'ended' }
  const target = start > currentTime.value ? start : due
  const prefix = start > currentTime.value ? '距开始' : '距结束'
  const minutes = Math.max(1, Math.ceil((target - currentTime.value) / 60000))
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const remainder = minutes % 60
  const duration = days ? `${days}天${hours ? `${hours}小时` : ''}` : hours ? `${hours}小时${remainder ? `${remainder}分钟` : ''}` : `${remainder}分钟`
  return { label: `${prefix} ${duration}`, state: start > currentTime.value ? 'upcoming' : minutes <= 1440 ? 'urgent' : 'active' }
}
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
const statusLabels = { ACTIVE: '进行中', ARCHIVED: '已归档', PENDING: '待处理', PENDING_REVIEW: '待处理', PENDING_COEFFICIENT: '待填系数', PENDING_ASSESSMENT: '待评分', PENDING_SUBMISSION: '待提交', NO_SUBMISSION: '未提交', GRADED: '已评分', CHANGED: '有未发布修改', APPROVED: '已通过', REJECTED: '已拒绝', CANCELLED: '已取消', DRAFT: '待发布', PUBLISHED: '已发布', SUBMITTED: '已提交', RETRACTED: '已撤回', VALID: '有效', INVALID: '已作废', CLOSED: '已结束', NOT_SUBMITTED: '未提交', LEFT: '已退出', DISBANDED: '已解散', NOT_STARTED: '未开始' }
const roleLabels = { LEADER: '组长', MEMBER: '组员', TEACHER: '教师', STUDENT: '学生', SYSTEM: '系统' }
const objectLabels = { user: '用户', class: '教学班', class_join_request: '入班申请', team: '小组', team_request: '组队申请', topic: '选题', assignment: '作业', submission: '作业提交', submission_assessment: '提交评价', review_campaign: '互评活动', peer_review: '作品评价', grade: '成绩' }
const actionLabels = { PASSWORD_CHANGED: '修改密码', PASSWORD_RESET: '重置密码', CLASS_CREATED: '创建教学班', CLASS_UPDATED: '更新教学班', CLASS_DELETED: '删除教学班', CLASS_JOIN_REQUESTED: '申请加入教学班', CLASS_JOINED_BY_INVITE: '通过邀请码入班', CLASS_JOIN_APPROVED: '同意入班申请', CLASS_JOIN_REJECTED: '拒绝入班申请', ROSTER_IMPORTED: '导入学生名单', CLASS_MEMBER_ADDED: '添加班级成员', CLASS_MEMBER_UPDATED: '更新成员信息', CLASS_MEMBER_REMOVED: '移出班级成员', TEAM_CREATED: '创建小组', TEAMS_AUTO_GROUPED: '自动分组', TEAM_REQUEST_DECIDED: '处理组队申请', TEAM_REQUEST_CANCELLED: '取消组队申请', TEAM_INVITATION_RESPONDED: '回应小组邀请', TEAM_LEADER_TRANSFERRED: '移交组长', TEAM_LEFT: '退出小组', TEAM_DISBANDED: '解散小组', TEAM_MEMBER_REMOVED: '移出小组成员', TOPIC_SUBMITTED: '提交选题', TOPIC_DECIDED: '审核选题', ASSIGNMENT_CREATED: '创建作业', ASSIGNMENT_UPDATED: '更新作业', ASSIGNMENT_PUBLISHED: '发布作业', ASSIGNMENT_RETRACTED: '撤回作业', ASSIGNMENT_CLOSED: '提前截止作业', ASSIGNMENT_DELETED: '删除作业', SUBMISSION_CREATED: '提交作业', SUBMISSION_RETRACTED: '撤回作业', SUBMISSIONS_EXPORTED: '导出作业', REVIEW_CAMPAIGN_CREATED: '创建互评活动', REVIEW_CAMPAIGN_AUTO_CREATED: '自动创建互评活动', REVIEW_CAMPAIGN_CLOSED: '提前截止互评', PEER_REVIEW_SUBMITTED: '提交作品评价', PEER_REVIEW_UPDATED: '更新作品评价', PEER_REVIEW_INVALIDATED: '作废作品评价', PEER_ASSESSMENT_SUBMITTED: '提交学生互评', PEER_ASSESSMENT_UPDATED: '更新学生互评', TEACHER_ASSESSMENT_SUBMITTED: '提交教师评分', TEACHER_ASSESSMENT_UPDATED: '更新教师评分', TEACHER_ASSESSMENT_CLEARED: '清除教师评分', TEACHER_FEEDBACK_DRAFT_SAVED: '保存教师反馈草稿', TEACHER_FEEDBACK_PUBLISHED: '发布教师反馈', PEER_GRADES_GENERATED: '生成互评成绩', GRADE_COEFFICIENT_UPDATED: '更新小组系数', GRADES_PUBLISHED: '发布成绩' }
function auditSearchParams() {
  const params = new URLSearchParams()
  const query = auditSearch.value.trim()
  if (query) {
    params.set('q', query)
    Object.entries(actionLabels).filter(([, label]) => label.includes(query)).forEach(([value]) => params.append('actions', value))
    Object.entries(objectLabels).filter(([, label]) => label.includes(query)).forEach(([value]) => params.append('object_types', value))
  }
  if (auditSemester.value !== 'ALL') params.set('semester', auditSemester.value)
  if (auditClassId.value !== 'ALL') params.set('class_id', auditClassId.value)
  if (auditActorRole.value !== 'ALL') params.set('actor_role', auditActorRole.value)
  return params
}
async function searchAudits() { auditPage.value = 1; await loadView() }
async function changeAuditSemester() {
  if (!auditClassOptions.value.some(item => item.value === auditClassId.value)) auditClassId.value = 'ALL'
  await searchAudits()
}
async function changeAuditPage(page) { auditPage.value = page; await loadView({ silent: true }) }
function statusLabel(value) { return statusLabels[value] || value || '-' }
function roleLabel(value) { return roleLabels[value] || value || '-' }
function objectLabel(value) { return objectLabels[value] || (value ? '其他业务对象' : '-') }
function actionLabel(value) { return actionLabels[value] || (value ? '其他系统操作' : '-') }
function gradeSourceLabel(value) { return value === 'TEACHER' ? '教师评分' : value === 'PEER' ? '学生互评' : value === 'SYSTEM' ? '系统判定' : '-' }
async function action(fn, success) {
  const originPath = route.fullPath
  const preserveTeacherDrawer = role.value === 'TEACHER' && view.value === 'assignment-detail'
  try {
    await fn()
    if (success) message.success(success)
    await Promise.all([originPath === route.fullPath ? loadView({ silent: preserveTeacherDrawer }) : Promise.resolve(), loadNotifications()])
  } catch (e) { message.error(e.message) }
}

async function loadNotifications() {
  if (!classId.value) { notifications.value = []; return }
  try {
    const noticeData = await api('/notifications')
    notifications.value = noticeData.items
  } catch (_) { /* Notification refresh must not block page navigation or completed actions. */ }
}

async function loadView({ silent = false, background = false } = {}) {
  const generation = ++loadGeneration
  const requestedKey = pageKey.value
  const isCurrent = () => generation === loadGeneration && requestedKey === pageKey.value
  if (!silent) loading.value = true
  try {
    if (!classId.value) return
    if (view.value === 'overview') {
      const dashboardData = await api(`/classes/${classId.value}/dashboard`)
      if (!isCurrent()) return
      dashboard.value = dashboardData
      if (role.value === 'STUDENT') {
        const [assignmentData, campaignData, gradeData, teamData] = await Promise.all([api(`/assignments?class_id=${classId.value}`), api(`/peer-review-assignments?class_id=${classId.value}`), api(`/grades?class_id=${classId.value}`), api(`/teams?class_id=${classId.value}`)])
        if (!isCurrent()) return
        assignments.value = assignmentData.items; campaigns.value = campaignData.items; grades.value = gradeData.items; teams.value = teamData.items
      }
    }
    if (view.value === 'classes') {
      const memberData = await api(`/classes/${classId.value}/members`)
      if (!isCurrent()) return
      members.value = memberData.items
    }
    if (view.value === 'teams') {
      const [t, r, memberData] = await Promise.all([api(`/teams?class_id=${classId.value}`), role.value === 'STUDENT' ? api(`/team-requests?class_id=${classId.value}`) : Promise.resolve({ items: [] }), role.value === 'TEACHER' ? api(`/classes/${classId.value}/members`) : Promise.resolve({ items: [] })])
      if (!isCurrent()) return
      teams.value = t.items; requests.value = r.items; members.value = memberData.items
      const linkedTeam = teams.value.find(item => item.id === route.query.team)
      if (linkedTeam) await openTeam(linkedTeam)
    }
    if (view.value === 'assignments') {
      const [assignmentData, gradeData] = await Promise.all([
        api(`/assignments?class_id=${classId.value}`),
        role.value === 'STUDENT' ? api(`/grades?class_id=${classId.value}`) : Promise.resolve({ items: [] })
      ])
      if (!isCurrent()) return
      assignments.value = assignmentData.items
      if (role.value === 'STUDENT') grades.value = gradeData.items
    }
    if (view.value === 'assignment-detail') {
      const assignmentData = await api(`/assignments?class_id=${classId.value}`)
      if (!isCurrent()) return
      assignments.value = assignmentData.items
      const assignment = assignments.value.find(item => item.id === detailId.value)
      if (!assignment) { message.error('作业不存在或无权查看'); await router.replace('/assignments') }
      else {
        const allowedTabs = ['details', 'submission']
        assignmentDetailTab.value = allowedTabs.includes(route.query.tab) ? route.query.tab : 'details'
        await loadAssignmentDetail(assignment, isCurrent, { preserveUi: background })
        const previewVersion = route.query.preview_submission
        const previewKey = `${assignment.id}:${previewVersion || ''}`
        if (previewVersion && isCurrent() && openedSubmissionPreview.value !== previewKey) {
          const record = assignment.board?.find(item => item.submission_version_id === previewVersion && item.status === 'SUBMITTED' && item.files?.length)
          openedSubmissionPreview.value = previewKey
          if (record) openSubmissionDetail(record)
          else message.warning('该提交暂无可预览文件')
        }
        const gradingVersion = route.query.grade_submission
        const gradingKey = `${assignment.id}:grading:${gradingVersion || ''}`
        if (gradingVersion && isCurrent() && openedSubmissionPreview.value !== gradingKey) {
          const targets = pendingTeacherReviewTargets(assignment.board)
          const record = targets.find(item => item.submission_version_id === gradingVersion)
          openedSubmissionPreview.value = gradingKey
          if (record) openAssessmentDrawer(record, { mode: 'TEACHER', targets, targetIndex: targets.indexOf(record), pendingOnly: true })
          else message.info('暂无待批改作业')
        }
      }
    }
    if (view.value === 'reviews') {
      if (role.value === 'TEACHER') { await router.replace('/assignments'); return }
      const campaignData = await api(`/peer-review-assignments?class_id=${classId.value}`)
      if (!isCurrent()) return
      campaigns.value = campaignData.items
    }
    if (view.value === 'review-detail') {
      if (role.value === 'TEACHER') { await router.replace('/assignments'); return }
      const campaignData = await api(`/peer-review-assignments?class_id=${classId.value}`)
      if (!isCurrent()) return
      campaigns.value = campaignData.items
      const assignment = campaigns.value.find(item => item.assignment_id === detailId.value)
      if (!assignment) { message.error('当前没有可互评的组员提交'); await router.replace('/reviews') }
      else await loadCampaignDetail(assignment, isCurrent)
    }
    if (view.value === 'grades') {
      const gradeData = role.value === 'TEACHER' ? await api(`/grades/assignments?class_id=${classId.value}`) : await api(`/grades?class_id=${classId.value}`)
      if (!isCurrent()) return
      if (role.value === 'TEACHER') gradeAssignments.value = gradeData.items
      else grades.value = gradeData.items
    }
    if (view.value === 'grade-detail') {
      if (role.value !== 'TEACHER') { await router.replace('/grades'); return }
      await router.replace({ name: 'assignment-detail', params: { id: detailId.value }, query: { tab: 'grades' } })
      return
    }
    if (view.value === 'system' && role.value === 'TEACHER') {
      const params = auditSearchParams()
      params.set('page', auditPage.value)
      params.set('page_size', auditPageSize)
      const auditData = await api(`/audit-logs?${params}`)
      if (!isCurrent()) return
      audits.value = auditData.items
      auditTotal.value = auditData.total
    }
  } catch (e) { if (!background) message.error(e.message) }
  finally {
    if (isCurrent()) {
      loadedViewKeys.add(requestedKey)
      loading.value = false
    }
  }
}

async function changeClass(id) {
  await session.refreshClasses(id)
  const target = session.teamGate ? '/teams' : '/overview'
  if (route.path === target) await loadView()
  else await router.replace(target)
  await loadNotifications()
}
async function manageClass(item) { await session.refreshClasses(item.id); await router.replace('/classes'); await loadView() }
function openClassCreate() {
  Object.assign(classForm, { id: '', version: 1, semester: '', name: '', team_deadline: '', topic_public: false }); modals.class = true
}
function openClassEdit(item) {
  Object.assign(classForm, { id: item.id, version: item.version, semester: item.semester, name: item.name, team_deadline: localDateTime(item.team_deadline), topic_public: item.topic_public }); modals.class = true
}
async function saveClass() {
  if (!classForm.semester.trim() || !classForm.name.trim()) return message.warning('请填写学期和班级名称')
  const payload = { semester: classForm.semester, name: classForm.name, team_deadline: iso(classForm.team_deadline), topic_public: classForm.topic_public }
  const editing = Boolean(classForm.id)
  await action(async () => {
    const saved = editing
      ? await api(`/classes/${classForm.id}`, { method: 'PATCH', body: JSON.stringify({ ...payload, version: classForm.version }) })
      : await api('/classes', { method: 'POST', body: JSON.stringify(payload) })
    modals.class = false; await session.refreshClasses(saved.id)
  }, editing ? '教学班资料已更新' : '教学班已创建')
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
  memberDetail.value = item
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
function removeClassMember(item) { Modal.confirm({ title: `将 ${item.name} 移出教学班？`, content: item.team ? `该成员也会退出小组「${item.team}」。` : '历史提交和成绩将继续保留。', okText: '确认移出', okType: 'danger', onOk: () => action(async () => { await api(`/classes/${classId.value}/members/${item.id}`, { method: 'DELETE' }); memberDetail.value = null }, '成员已移出') }) }
async function createTeam() {
  await action(async () => { await api('/teams', { method: 'POST', body: JSON.stringify({ class_id: classId.value, ...teamForm }) }); modals.team = false; await session.refreshContext(); await router.replace('/overview') }, '小组已创建')
}
async function applyTeam(item) { await action(() => api(`/teams/${item.id}/applications`, { method: 'POST' }), '申请已提交') }
async function cancelRequest(item) { await action(() => api(`/team-requests/${item.id}`, { method: 'DELETE' }), '申请已取消') }
async function decideRequest(item, decision) { await action(() => api(`/team-requests/${item.id}/decision?decision=${decision}`, { method: 'POST' }), decision === 'APPROVED' ? '已同意申请' : '已拒绝申请') }
async function openTeam(item) {
  const generation = ++teamRequestGeneration
  teamDrawerLoading.value = true
  selectedTeamAssignments.value = []
  try {
    selectedTeam.value = await api(`/teams/${item.id}`)
    topicForm.name = item.topic?.name || ''
    topicForm.description = item.topic?.description || ''
    if (item.is_leader || role.value === 'TEACHER') members.value = (await api(`/classes/${classId.value}/members`)).items
    if (role.value === 'TEACHER') {
      const assignmentData = await api(`/assignments?class_id=${classId.value}`)
      const recentAssignments = assignmentData.items.filter(assignment => assignment.submitter_type === 'TEAM' && assignment.status !== 'DRAFT').slice(0, 5)
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
function closeTeamDrawer() { teamRequestGeneration++; selectedTeam.value = null; selectedTeamAssignments.value = []; teamDrawerLoading.value = false }
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
  Object.assign(assignmentForm, { id: '', version: 1, has_submissions: false, class_ids: defaultClassSelection(), title: '', description: '', submitter_type: 'INDIVIDUAL', starts_at: '', due_at: '', allow_late: false, publish: false, auto_review_enabled: false, auto_review_mode: 'TEAM', auto_review_criteria_text: '', auto_review_due_at: '' }); pendingAssignmentFiles.value = []; descriptionEditor.value?.commands.setContent('', { emitUpdate: false }); modals.assignment = true
}
function openAssignmentEdit() {
  const item = selectedAssignment.value
  Object.assign(assignmentForm, { id: item.id, version: item.version, has_submissions: (item.board || []).some(record => record.status === 'SUBMITTED'), class_ids: [item.class_id], title: item.title, description: item.description, submitter_type: item.submitter_type, starts_at: localDateTime(item.starts_at), due_at: localDateTime(item.due_at), allow_late: item.allow_late, publish: item.status === 'PUBLISHED', auto_review_enabled: item.auto_review_enabled, auto_review_mode: item.auto_review_mode || 'TEAM', auto_review_criteria_text: item.auto_review_criteria_text || '', auto_review_due_at: localDateTime(item.auto_review_due_at) })
  descriptionEditor.value?.commands.setContent(item.description || '', { emitUpdate: false }); pendingAssignmentFiles.value = []; modals.assignment = true
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
async function createAssignment(publishRequested = false) {
  if (!assignmentForm.id && !assignmentForm.class_ids.length) return message.warning('请至少选择一个教学班')
  if (assignmentForm.title.trim().length < 2) return message.warning('标题至少填写 2 个字符')
  const descriptionText = descriptionEditor.value?.getText().trim() || ''
  if (!descriptionText) return message.warning('请填写作业说明')
  if (!assignmentForm.due_at) return message.warning('请选择截止时间')
  if (assignmentForm.submitter_type === 'TEAM' && new Date(assignmentForm.due_at) <= new Date() && (publishRequested || (assignmentForm.id && selectedAssignment.value?.status === 'PUBLISHED'))) return message.warning('小组作业截止时间必须晚于当前时间')
  if (assignmentForm.starts_at && new Date(assignmentForm.starts_at) >= new Date(assignmentForm.due_at)) return message.warning('开始时间必须早于截止时间')
  if (assignmentForm.auto_review_enabled) {
    if (!assignmentForm.auto_review_due_at || new Date(assignmentForm.auto_review_due_at) <= new Date(assignmentForm.due_at)) return message.warning('互评截止时间必须晚于作业截止时间')
    if (!assignmentForm.auto_review_criteria_text.trim() && (!assignmentForm.id || !reviewCriteriaFiles.value.length)) return message.warning('自动互评标准文字和附件至少提供一种')
  }
  if (assignmentForm.id) {
    await action(async () => {
      const payload = { title: assignmentForm.title, description: assignmentForm.description, submitter_type: assignmentForm.submitter_type, starts_at: iso(assignmentForm.starts_at), due_at: iso(assignmentForm.due_at), allow_late: assignmentForm.allow_late, version: assignmentForm.version }
      if (reviewConfigEditable.value) Object.assign(payload, { auto_review_enabled: assignmentForm.auto_review_enabled, auto_review_mode: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_mode : null, auto_review_criteria_text: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_criteria_text : '', auto_review_due_at: assignmentForm.auto_review_enabled ? iso(assignmentForm.auto_review_due_at) : null })
      const saved = await api(`/assignments/${assignmentForm.id}`, { method: 'PATCH', body: JSON.stringify(payload) })
      assignmentForm.version = saved.version
      while (pendingAssignmentFiles.value.length) {
        const file = pendingAssignmentFiles.value[0]
        const body = new FormData(); body.append('file', file)
        const attachment = await api(`/assignments/${assignmentForm.id}/files`, { method: 'POST', body })
        assignmentAttachments.value.push(attachment)
        pendingAssignmentFiles.value.shift()
      }
      if (publishRequested) await api(`/assignments/${assignmentForm.id}/publish`, { method: 'POST' })
      modals.assignment = false
    }, publishRequested ? '作业已更新并重新发布' : '作业已更新')
    return
  }
  const count = assignmentForm.class_ids.length
  const createPayload = {
    class_ids: [...assignmentForm.class_ids],
    title: assignmentForm.title.trim(),
    description: assignmentForm.description,
    submitter_type: assignmentForm.submitter_type,
    starts_at: iso(assignmentForm.starts_at),
    due_at: iso(assignmentForm.due_at),
    allow_late: assignmentForm.allow_late,
    publish: false,
    auto_review_enabled: assignmentForm.auto_review_enabled,
    auto_review_mode: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_mode : null,
    auto_review_criteria_text: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_criteria_text : '',
    auto_review_due_at: assignmentForm.auto_review_enabled ? iso(assignmentForm.auto_review_due_at) : null
  }
  try {
    const created = await api('/assignments/bulk', { method: 'POST', body: JSON.stringify(createPayload) })
    const failed = []
    for (const assignment of created.items) {
      for (const file of pendingAssignmentFiles.value) {
        try {
          const body = new FormData(); body.append('file', file)
          await api(`/assignments/${assignment.id}/files`, { method: 'POST', body })
        } catch (error) { failed.push(`${assignment.title}：${file.name}（${error.message}）`) }
      }
    }
    if (!failed.length && publishRequested) await Promise.all(created.items.map(item => api(`/assignments/${item.id}/publish`, { method: 'POST' })))
    pendingAssignmentFiles.value = []; modals.assignment = false; await session.refreshClasses(classId.value); await loadView()
    if (failed.length) message.warning(`草稿已保留，${failed.length} 个附件上传失败，可在作业详情中重试后发布`)
    else message.success(publishRequested ? `已向 ${count} 个教学班发布作业` : `已为 ${count} 个教学班保存草稿`)
  } catch (error) { message.error(error.message) }
}
async function loadAssignmentDetail(item, isStillCurrent = () => true, { preserveUi = false } = {}) {
  selectedAssignment.value = item
  if (!preserveUi) {
    selectedSubmission.value = null; selectedCampaign.value = null; boardFilter.value = 'ALL'; boardTeamFilter.value = 'ALL'; boardQuery.value = ''
  }
  if (role.value === 'STUDENT') {
    const [files, submission] = await Promise.all([api(`/assignments/${item.id}/files`), api(`/assignments/${item.id}/submission`)])
    if (!isStillCurrent()) return
    assignmentAttachments.value = files.attachments; reviewCriteriaFiles.value = files.review_criteria || []; draftFiles.value = files.drafts
    item.submission = submission
  }
  else {
    const [files, boardData, teamData] = await Promise.all([api(`/assignments/${item.id}/files`), api(`/assignments/${item.id}/submissions`), api(`/teams?class_id=${item.class_id}`)])
    if (!isStillCurrent()) return
    assignmentAttachments.value = files.attachments; reviewCriteriaFiles.value = files.review_criteria || []; draftFiles.value = files.drafts
    item.board = boardData.items; teams.value = teamData.items
    if (preserveUi && filePreview.open && selectedSubmission.value) {
      const refreshed = boardData.items.find(record => record.user_id && record.user_id === selectedSubmission.value.user_id)
      if (refreshed) requestAnimationFrame(() => fileReviewDrawer.value?.handleExternalSubmission?.(refreshed))
    }
  }
}
function changeAssignmentDetailTab(key) {
  assignmentDetailTab.value = key
  router.replace({ name: 'assignment-detail', params: { id: selectedAssignment.value.id }, query: key === 'details' ? {} : { tab: key } })
}
async function openAssignment(item, tab = 'details') {
  selectedAssignment.value = item
  assignmentDetailTab.value = tab
  const query = tab === 'details' ? {} : { tab }
  await router.push({ name: 'assignment-detail', params: { id: item.id }, query })
}
async function closeAssignmentDrawer() { await router.push('/assignments') }
async function uploadFile({ file, onSuccess, onError }) {
  try {
    const body = new FormData(); body.append('file', file); const saved = await api(`/assignments/${selectedAssignment.value.id}/files`, { method: 'POST', body })
    if (role.value === 'TEACHER') assignmentAttachments.value.push(saved)
    else draftFiles.value.push(saved)
    onSuccess(saved)
  } catch (e) { onError(e); message.error(e.message) }
}
const deletingMaterials = ref(false)
function deleteSelectedMaterials(files) {
  if (!files.length || deletingMaterials.value) return
  const assignment = selectedAssignment.value
  Modal.confirm({
    title: `确认删除 ${files.length} 个作业资料附件？`,
    content: '删除后无法恢复，学生提交记录不受影响。',
    okText: '确认删除', okType: 'danger', cancelText: '取消',
    onOk: async () => {
      if (deletingMaterials.value) return
      deletingMaterials.value = true
      try {
        const results = await Promise.allSettled(files.map(file => api(`/files/${file.id}`, { method: 'DELETE' })))
        await loadAssignmentDetail(assignment)
        const failed = results.filter(result => result.status === 'rejected')
        if (failed.length) message.error(`${files.length-failed.length} 个附件已删除，${failed.length} 个删除失败：${failed[0].reason.message}`)
        else message.success(`已删除 ${files.length} 个附件`)
      } catch (error) { message.error(error.message) }
      finally { deletingMaterials.value = false }
    }
  })
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
  Modal.confirm({ title: updating ? '确认更新提交？' : '确认正式提交？', content: `将以当前 ${draftFiles.value.length} 个附件${updating?'覆盖原提交内容':'完成正式提交'}。`, okText: updating ? '确认更新' : '确认提交', cancelText: '继续检查', onOk: async () => action(async () => { await api(`/assignments/${selectedAssignment.value.id}/submission`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() }, body: JSON.stringify({}) }); await loadAssignmentDetail(selectedAssignment.value) }, updating ? '提交已更新' : '提交成功') })
}
function openSubmissionDetail(record) {
  const targets = (selectedAssignment.value?.board || []).filter(item => item.status === 'SUBMITTED' && item.files?.length)
  const targetIndex = Math.max(0, targets.findIndex(item => item.submission_version_id === record.submission_version_id))
  openAssessmentDrawer(record, { mode: 'TEACHER', targets, targetIndex })
}
function pendingTeacherReviewTargets(board = selectedAssignment.value?.board || []) {
  return board.filter(item => item.status === 'SUBMITTED' && item.files?.length && !item.teacher_grade)
}
async function continueGrading(item) {
  try {
    const board = await api(`/assignments/${item.id}/submissions`)
    const targets = pendingTeacherReviewTargets(board.items)
    if (!targets.length) return message.info('暂无待批改作业')
    await router.push({ name: 'assignment-detail', params: { id: item.id }, query: { tab: 'submission', grade_submission: targets[0].submission_version_id } })
  } catch (error) { message.error(error.message) }
}
function openStudentFeedback(record, peerFeedback = null) {
  const combined = !peerFeedback && record.teacher_grade && record.files?.length
  const submission = { ...record, owner: peerFeedback?.evaluator_name || record.assignment_title, peer_feedbacks: record.peer_feedbacks || [] }
  openAssessmentDrawer(submission, { mode: combined ? 'TEACHER' : peerFeedback ? 'PEER' : 'TEACHER', initialFeedback: peerFeedback })
}
function openStudentAssignment(item) {
  const grade = grades.value.find(record => record.assignment_id === item.id)
  const hasFeedback = grade && ((grade.teacher_grade && grade.files?.length) || grade.peer_feedbacks?.length)
  if (item.status === 'CLOSED' || new Date(item.due_at) <= new Date()) {
    if (hasFeedback) return openStudentFeedback(grade)
  }
  return openAssignment(item, 'details')
}
function openPeerReviewDrawer(candidate, file = candidate?.files?.[0]) {
  if (!candidate?.files?.length || !file) return message.warning('该组员没有可预览的提交文件')
  const submission = { ...candidate, owner: candidate.name }
  openAssessmentDrawer(submission, { mode: 'PEER', file })
}
function openAssessmentDrawer(record, { mode, targets = [], targetIndex = 0, initialFeedback = null, file = record.files?.[0], pendingOnly = false } = {}) {
  selectedSubmission.value = record
  filePreview.mode = mode
  filePreview.targets = targets
  filePreview.targetIndex = targetIndex
  filePreview.initialFeedback = initialFeedback
  filePreview.pendingOnly = pendingOnly
  filePreview.readonly = false
  filePreview.assignmentTitle = ''
  filePreview.files = [...(record.files || [])]
  filePreview.index = Math.max(0, filePreview.files.findIndex(item => item.id === file?.id))
  filePreview.open = true
}
function changeReviewTarget(targetIndex) {
  const record = filePreview.targets[targetIndex]
  if (!record) return
  selectedSubmission.value = record
  filePreview.targetIndex = targetIndex
  filePreview.files = [...record.files]
  filePreview.index = 0
  filePreview.initialFeedback = null
}
function handleExternalReviewTarget(record) {
  selectedSubmission.value = record
  const targets = filePreview.pendingOnly ? pendingTeacherReviewTargets() : selectedAssignment.value?.board?.filter(item => item.status === 'SUBMITTED' && item.files?.length) || []
  const targetIndex = Math.max(0, targets.findIndex(item => item.submission_version_id === record.submission_version_id))
  Object.assign(filePreview, { targets, targetIndex, files: [...(record.files || [])], index: 0, initialFeedback: null })
}
async function handleFeedbackPublished(result) {
  if (selectedSubmission.value && result) Object.assign(selectedSubmission.value, result)
  if (role.value === 'TEACHER' && selectedAssignment.value) await refreshSubmissionBoard()
  if (filePreview.mode === 'PEER' && view.value === 'review-detail' && selectedCampaign.value) await loadCampaignDetail(selectedCampaign.value, () => true, selectedSubmission.value?.user_id)
}
async function clearTeacherGrade() {
  try {
    const path = selectedAssignment.value.submitter_type === 'TEAM'
      ? `/submission-versions/${selectedSubmission.value.submission_version_id}/feedback`
      : `/assignments/${selectedAssignment.value.id}/submissions/${selectedSubmission.value.user_id}/grade`
    const result = await api(path, { method: 'DELETE' })
    Object.assign(selectedSubmission.value, result)
    await refreshSubmissionBoard()
    closeFilePreview()
    message.success(result.final_grade ? '已恢复由互评成绩决定' : '教师评分已清除，当前暂无互评成绩')
  } catch (error) { message.error(error.message) }
}
async function refreshSubmissionBoard() {
  const board = await api(`/assignments/${selectedAssignment.value.id}/submissions`)
  selectedAssignment.value.board = board.items
}
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
async function loadCampaignDetail(item, isStillCurrent = () => true, preferredUserId = '') {
  const task = await api(`/assignments/${item.assignment_id}/peer-review`)
  if (!isStillCurrent()) return
  selectedCampaign.value = item
  reviewTask.value = task
  const first = task.candidates.find(candidate => candidate.user_id === preferredUserId) || task.candidates[0]
  Object.assign(reviewForm, { reviewee_id: first?.user_id || '', grade: first?.review?.grade || 'A', comment: first?.review?.comment || '' })
}
async function openCampaign(item) {
  await router.push(`/reviews/${item.assignment_id}`)
}
function selectReviewCandidate(userId) {
  const candidate = reviewTask.value?.candidates?.find(item => item.user_id === userId)
  Object.assign(reviewForm, { reviewee_id: userId, grade: candidate?.review?.grade || 'A', comment: candidate?.review?.comment || '' })
}
async function submitReview() {
  if (!reviewForm.reviewee_id) return message.warning('请选择要评价的组员')
  const updating = Boolean(selectedReviewCandidate.value?.review)
  await action(async () => { await api(`/assignments/${selectedCampaign.value.assignment_id}/peer-reviews`, { method: 'POST', body: JSON.stringify(reviewForm) }); await loadCampaignDetail(selectedCampaign.value) }, updating ? '评价已更新' : '评价已提交')
}
async function readAll() {
  try {
    await api('/notifications/read', { method: 'POST' })
    notifications.value = notifications.value.map(item => ({ ...item, read: true }))
    await loadNotifications()
    message.success('已全部标为已读')
    noticesOpen.value = false
  } catch (error) { message.error(error.message) }
}
async function openNotification(item) {
  if (!item.link) return
  noticesOpen.value = false
  await router.push(item.link)
}
async function changePassword() { await action(async () => { await api('/auth/password', { method: 'POST', body: JSON.stringify(passwordForm) }); modals.password = false; await session.logout(); await router.replace('/login') }, '密码已修改，请重新登录') }
async function logout() { try { await session.logout() } finally { await router.replace('/login') } }
function downloadExport(kind, format = 'xlsx') {
  const assignment = kind === 'grades' && selectedGradeAssignmentId.value ? `&assignment_id=${selectedGradeAssignmentId.value}` : ''
  window.location.href = `/api/v1/exports/${kind}.${format}?class_id=${classId.value}${assignment}`
}
async function downloadTeamCoursework(item) {
  if (!item || exportingTeamIds.has(item.id)) return
  exportingTeamIds.add(item.id)
  try {
    const response = await fetch(`/api/v1/teams/${item.id}/coursework.zip`, { credentials: 'include', headers: { 'X-Client-ID': apiClientId } })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.message || data?.detail?.message || '当前无法导出，请稍后重试')
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${item.name}-全部作业与成绩.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    message.success('导出文件已生成')
  } catch (error) {
    message.warning(error.message || '当前无法导出，请稍后重试')
  } finally {
    exportingTeamIds.delete(item.id)
  }
}
function openFilePreview(file, files) {
  filePreview.mode = 'PREVIEW'
  filePreview.targets = []
  filePreview.targetIndex = 0
  filePreview.initialFeedback = null
  filePreview.pendingOnly = false
  filePreview.readonly = true
  filePreview.assignmentTitle = ''
  filePreview.files = [...(files || [])]
  filePreview.index = Math.max(0, filePreview.files.findIndex(item => item.id === file.id))
  filePreview.open = true
}
function openPortfolioFilePreview(file, files, assignment) {
  const submission = {
    owner: memberDetail.value?.name || '',
    user_id: memberDetail.value?.id || '',
    submission_version_id: assignment.submission_version_id,
    files: [...files],
    teacher_grade: assignment.teacher_grade,
    peer_grade: assignment.peer_grade,
    peer_feedbacks: assignment.received_reviews || []
  }
  selectedSubmission.value = submission
  Object.assign(filePreview, { mode: 'TEACHER', targets: [], targetIndex: 0, initialFeedback: assignment.teacher_grade, pendingOnly: false, readonly: true, assignmentTitle: assignment.title, files: [...files], index: Math.max(0, files.findIndex(item => item.id === file.id)), open: true })
}
function closeFilePreview() {
  filePreview.open = false
  selectedSubmission.value = null
}
function navigate(target) { return router.push(target) }
function openLatestSubmission() {
  const submission = dashboard.value?.summary?.latest_submission
  if (!submission) return
  return router.push({ name: 'assignment-detail', params: { id: submission.assignment_id }, query: { tab: 'submission', grade_submission: submission.submission_version_id } })
}

async function pollGate() {
  if (!session.teamGate) return
  const before = session.teamGate
  await session.refreshContext()
  if (before && !session.teamGate) { message.success('已加入小组'); clearInterval(gateTimer); await router.replace('/overview') }
}

function currentViewUses(scopes) {
  if (scopes.includes('current_view')) return true
  const needed = {
    overview: ['dashboard', 'assignments', 'submissions', 'reviews', 'grades', 'teams'],
    classes: ['classes', 'members'],
    teams: ['teams', 'members'],
    assignments: ['assignments', 'submissions'],
    'assignment-detail': ['assignments', 'submissions', 'reviews', 'grades', 'teams'],
    reviews: ['reviews', 'submissions'],
    'review-detail': ['reviews', 'submissions'],
    grades: ['grades'],
    system: ['audit']
  }
  return (needed[view.value] || []).some(scope => scopes.includes(scope))
}

async function flushRealtimeRefresh() {
  clearTimeout(realtimeTimer)
  realtimeTimer = undefined
  if (document.hidden) { realtimeDirty = true; return }
  const scopes = [...pendingRealtimeScopes]
  pendingRealtimeScopes.clear()
  realtimeDirty = false
  await Promise.all([
    currentViewUses(scopes) ? loadView({ silent: true, background: true }) : Promise.resolve(),
    scopes.includes('notifications') || scopes.includes('current_view') ? loadNotifications() : Promise.resolve()
  ])
}

function scheduleRealtimeRefresh(scopes = ['current_view', 'notifications']) {
  scopes.forEach(scope => pendingRealtimeScopes.add(scope))
  if (document.hidden) { realtimeDirty = true; return }
  clearTimeout(realtimeTimer)
  realtimeTimer = setTimeout(flushRealtimeRefresh, 500)
}

function handleRealtimeEvent(event) {
  try {
    const payload = JSON.parse(event.data || '{}')
    if (payload.source_client_id && payload.source_client_id === apiClientId) return
    scheduleRealtimeRefresh(payload.scopes)
  } catch (_) { scheduleRealtimeRefresh() }
}

function connectRealtime() {
  realtimeSource?.close()
  realtimeSource = undefined
  if (!session.user || !classId.value) return
  realtimeSource = new EventSource(`/api/v1/events?class_id=${encodeURIComponent(classId.value)}`)
  realtimeSource.addEventListener('invalidate', handleRealtimeEvent)
  realtimeSource.addEventListener('sync_required', handleRealtimeEvent)
  realtimeSource.addEventListener('auth_expired', () => window.dispatchEvent(new CustomEvent('auth-expired')))
}

function handleVisibilitySync() {
  if (!document.hidden && (realtimeDirty || pendingRealtimeScopes.size)) flushRealtimeRefresh()
}

function startSafetyRefresh() {
  clearInterval(safetyTimer)
  safetyTimer = setInterval(() => {
    if (!document.hidden) scheduleRealtimeRefresh(['current_view', 'notifications'])
  }, 300000 + Math.floor(Math.random() * 30000))
}

watch(() => route.path, (path, previousPath) => {
  const opensTeacherDrawer = role.value === 'TEACHER' && ['/assignments', '/overview', '/'].includes(previousPath) && path.startsWith('/assignments/')
  const closesTeacherDrawer = role.value === 'TEACHER' && path === '/assignments' && previousPath?.startsWith('/assignments/')
  loadView({ silent: opensTeacherDrawer || closesTeacherDrawer })
})
watch(() => route.query.tab, tab => {
  if (view.value !== 'assignment-detail') return
  const allowedTabs = role.value === 'TEACHER' ? ['details', 'submission', 'reviews', 'grades'] : ['details', 'submission']
  assignmentDetailTab.value = allowedTabs.includes(tab) ? tab : 'details'
})
watch(() => route.path, () => { memberDetail.value = null; if (view.value !== 'assignment-detail') openedSubmissionPreview.value = '' })
watch(() => session.teamGate, required => { clearInterval(gateTimer); gateTimer = required ? setInterval(pollGate, 10000) : undefined })
watch(classId, () => { memberDetail.value = null; connectRealtime() })
onMounted(async () => {
  await Promise.all([loadView(), loadNotifications()])
  if (session.teamGate) gateTimer = setInterval(pollGate, 10000)
  clockTimer = setInterval(() => { currentTime.value = Date.now() }, 30000)
  window.addEventListener('focus', pollGate)
  document.addEventListener('visibilitychange', handleVisibilitySync)
  connectRealtime(); startSafetyRefresh()
})
onBeforeUnmount(() => {
  clearInterval(gateTimer); clearInterval(clockTimer); clearInterval(safetyTimer); clearTimeout(realtimeTimer)
  realtimeSource?.close()
  window.removeEventListener('focus', pollGate)
  document.removeEventListener('visibilitychange', handleVisibilitySync)
  closeFilePreview()
})

provide(shellContextKey, {
  session, role, classId, menu, navView, notifications, noticesOpen, modals, audits, auditSearch, auditSemester, auditClassId, auditActorRole, auditSemesterOptions, auditClassOptions, auditPage, auditPageSize, auditTotal, loading, dashboard, memberQuery, filteredMembers,
  teams, requests, ungroupedMembers, selectedTeam, selectedTeamAssignments, teamDrawerLoading, exportingTeamIds,
  activeClasses, assignments,
  grades, gradeAssignments, selectedGradeAssignmentId, campaigns, selectedCampaign, reviewTask, reviewForm, selectedReviewCandidate,
  latestOverviewAssignment, assignmentHistory, assignmentChartLine, assignmentChartPoints, currentTeam, needsTopicSubmission,
  studentPendingAssignments, studentUpcomingAssignments, studentPendingReviews, studentLatestGrade,
  changeClass, logout, navigate, formatTime, actionLabel, objectLabel, statusLabel, roleLabel, gradeSourceLabel, searchAudits, changeAuditSemester, changeAuditPage, downloadExport, downloadTeamCoursework, openStudentFeedback, openStudentAssignment, openClassCreate,
  manageClass, openClassEdit, toggleClassStatus, deleteClass, openMemberCreate, openMemberDetail, openMemberEdit, resetMemberPassword, removeClassMember,
  applyTeam, openTeam, closeTeamDrawer, decideTopic, decideRequest, respondInvitation, cancelRequest, openAssignmentCreate, assignmentStateClass, openAssignment, assignmentCountdown,
  openCampaign, selectReviewCandidate, openFilePreview, openPeerReviewDrawer, submitReview, openLatestSubmission, continueGrading
})
</script>

<template>
  <a-layout v-if="session.user" class="app-shell">
    <ShellHeader />
    <a-layout-content class="app-content"><div class="content-wrap">
      <div v-if="loading&&!initialLoading" class="page-progress" role="progressbar" aria-label="正在刷新页面数据"><span/></div>
      <a-skeleton v-if="initialLoading" class="page-skeleton" active :paragraph="{rows:8}"/>
      <Transition v-else name="page-fade" mode="out-in">
      <div :key="surfaceKey" class="page-surface" :aria-busy="loading">
      <OverviewPage v-if="view==='overview'" />

      <ClassesPage v-else-if="view==='classes'&&role==='TEACHER'" />

      <TeamsPage v-else-if="view==='teams'" />

      <AssignmentsPage v-else-if="view==='assignments'||(view==='assignment-detail'&&role==='TEACHER')" />

      <template v-if="view==='assignment-detail'&&selectedAssignment">
        <template v-if="role==='TEACHER'">
          <Transition name="drawer-fade" appear><div class="assignment-drawer-mask" @click="closeAssignmentDrawer"></div></Transition>
        </template>
        <Transition :name="role==='TEACHER'?'drawer-slide':'detail-fade'" appear>
        <div :class="{'assignment-detail-drawer':role==='TEACHER'}">
         <div class="page-title detail-title"><div><div class="eyebrow">作业详情</div><h1>{{selectedAssignment.title}}</h1><div class="assignment-title-meta"><a-tag color="blue">{{selectedAssignment.submitter_type==='INDIVIDUAL'?'个人作业':'小组作业'}}</a-tag><a-tag :color="selectedAssignment.status==='PUBLISHED'?'green':'default'">{{statusLabel(selectedAssignment.status)}}</a-tag><span>截止 {{formatTime(selectedAssignment.due_at)}}</span><a-tag v-if="selectedAssignment.allow_late">允许迟交</a-tag></div></div><a-button @click="router.push('/assignments')"><ArrowLeftOutlined/> 返回作业列表</a-button></div>
         <section class="assignment-workspace">
           <a-tabs :active-key="assignmentDetailTab" :animated="{inkBar:true,tabPane:true}" class="assignment-detail-tabs" @change="changeAssignmentDetailTab">
            <a-tab-pane key="details" :tab="role==='TEACHER'?'详情':'作业详情'">
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业说明</h2></div>
                <div class="rich-text detail-description" v-html="selectedAssignment.description"></div>
              </section>
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业资料</h2><a-space><span v-if="assignmentAttachments.length">{{assignmentAttachments.length}} 个附件</span><a-upload v-if="role==='TEACHER'" :custom-request="uploadFile" :show-upload-list="false" multiple><a-button><UploadOutlined/> 上传作业附件</a-button></a-upload></a-space></div>
                <a-empty v-if="!assignmentAttachments.length" class="detail-empty" description="暂无作业资料"/>
                <AssignmentMaterials v-else :files="assignmentAttachments" :assignment-id="selectedAssignment.id" :can-delete="role==='TEACHER'" :deleting="deletingMaterials" @preview="openFilePreview" @delete="deleteDraft" @delete-selected="deleteSelectedMaterials"/>
              </section>
              <section v-if="role==='TEACHER'" class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业操作</h2></div>
                <a-space wrap><a-button @click="openAssignmentEdit"><EditOutlined/> 编辑作业</a-button><a-button v-if="selectedAssignment.status==='DRAFT'" type="primary" @click="publishAssignment">发布作业</a-button><a-button v-if="selectedAssignment.status==='PUBLISHED'&&new Date(selectedAssignment.due_at)>new Date()" danger @click="closeAssignment">提前截止</a-button><a-button v-if="['PUBLISHED','CLOSED'].includes(selectedAssignment.status)" danger @click="retractAssignment">撤回发布</a-button><a-button danger @click="deleteAssignment"><DeleteOutlined/> 删除作业</a-button></a-space>
              </section>
            </a-tab-pane>
            <a-tab-pane key="submission" :tab="role==='TEACHER'?'提交情况':'提交作业'">
              <template v-if="role==='TEACHER'">
                <section class="assignment-pane teacher-submission-pane">
                  <div class="assignment-pane-heading"><h2>提交概览</h2><a-space wrap><a-button :href="`/api/v1/assignments/${selectedAssignment.id}/download.zip`"><DownloadOutlined/> 下载全部学生作业</a-button><a-button v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" :href="`/api/v1/exports/grades.xlsx?class_id=${classId}&assignment_id=${selectedAssignment.id}`"><DownloadOutlined/> 导出所有学生成绩</a-button></a-space></div>
                  <div class="detail-metrics"><div><span>应提交</span><strong>{{teacherSubmissionSummary.total}}</strong></div><div><span>已提交</span><strong>{{teacherSubmissionSummary.submitted}}</strong></div><div><span>未提交</span><strong>{{teacherSubmissionSummary.pending}}</strong></div><div><span>迟交</span><strong>{{teacherSubmissionSummary.late}}</strong></div></div>
                </section>
                <section class="assignment-pane">
                  <div class="assignment-pane-heading"><h2>提交明细</h2></div>
                  <div class="board-toolbar"><a-input-search v-model:value="boardQuery" allow-clear placeholder="搜索姓名或学号"/><a-select v-model:value="boardTeamFilter" :options="boardTeamOptions"/><a-segmented v-model:value="boardFilter" :options="[{label:'全部',value:'ALL'},{label:'未提交',value:'NOT_SUBMITTED'},{label:'已提交',value:'SUBMITTED'},{label:'迟交',value:'LATE'}]"/></div>
                  <a-empty v-if="!groupedBoard.length" class="detail-empty" description="没有符合条件的提交记录"/>
                  <section v-for="group in groupedBoard" :key="group.id" class="submission-group"><div class="submission-group-heading"><strong>{{group.name}}</strong><span>{{group.items.length}} 人</span></div><a-table :data-source="group.items" row-key="id" size="small" :pagination="false"><a-table-column title="提交对象" data-index="owner"/><a-table-column v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" title="学号"><template #default="{record}">{{record.student_no||'-'}}</template></a-table-column><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag><a-tag v-if="record.is_late" color="red">迟交</a-tag></template></a-table-column><a-table-column v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" title="互评"><template #default="{record}">{{record.peer_grade||'-'}}<small v-if="record.peer_review_count">（{{record.peer_review_count}} 人）</small></template></a-table-column><a-table-column v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" title="最终成绩"><template #default="{record}"><a-tag v-if="record.final_grade" :color="record.grade_source==='TEACHER'?'green':record.grade_source==='SYSTEM'?'red':'blue'">{{record.final_grade}} · {{gradeSourceLabel(record.grade_source)}}</a-tag><a-tag v-else color="gold">{{statusLabel(record.grading_status)}}</a-tag></template></a-table-column><a-table-column title="提交时间"><template #default="{record}">{{formatTime(record.submitted_at)}}</template></a-table-column><a-table-column title="操作" :width="110"><template #default="{record}"><a-button v-if="record.status==='SUBMITTED'" type="link" @click="openSubmissionDetail(record)"><EyeOutlined/> 查看作业</a-button><span v-else>-</span></template></a-table-column></a-table></section>
                </section>
              </template>
              <template v-else>
              <div class="submission-summary" :class="{submitted:assignmentSubmitted,closed:!canSubmitAssignment&&!assignmentSubmitted}"><span class="submission-summary-icon"><CheckCircleOutlined v-if="assignmentSubmitted"/><InboxOutlined v-else/></span><div><strong>{{assignmentSubmitted?'已提交':!canManageTeamSubmission?'待组长提交':new Date(selectedAssignment.due_at)<=new Date()?'已截止':'待提交'}}</strong><span>{{assignmentSubmitted?`${formatTime(selectedAssignment.submission?.submitted_at)} · ${draftFiles.length} 个附件`:!canManageTeamSubmission?'小组作业仅需组长统一上交':`截止 ${formatTime(selectedAssignment.due_at)}`}}</span></div></div>
              <section class="assignment-pane submission-files-pane">
                <div class="assignment-pane-heading"><h2>提交附件</h2><a-upload v-if="canSubmitAssignment" :custom-request="uploadFile" accept=".md,.html,.htm,.pdf,.png,.jpg,.jpeg,.gif,.webp" multiple><a-button><UploadOutlined/> 上传附件</a-button></a-upload></div>
                <a-empty v-if="!draftFiles.length" class="detail-empty" description="暂无提交附件"/>
                <div v-else class="assignment-file-list"><div v-for="file in draftFiles" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openFilePreview(file,draftFiles)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button><a-tooltip v-if="canSubmitAssignment" :title="file.submitted?'从待更新附件中移除':'删除附件'"><a-button danger type="text" shape="circle" @click="deleteDraft(file)"><DeleteOutlined/></a-button></a-tooltip></div></div>
                <div v-if="canSubmitAssignment" class="submission-actions"><a-button type="primary" :disabled="!draftFiles.length" @click="submitAssignment">{{assignmentIsUpdate?'更新提交':'提交'}}</a-button></div>
              </section>
              </template>
            </a-tab-pane>
          </a-tabs>
        </section>
        </div>
        </Transition>
      </template>

      <ReviewsPage v-else-if="view==='reviews'" />
      <ReviewDetailPage v-else-if="view==='review-detail'&&selectedCampaign" />

      <GradesPage v-else-if="view==='grades'" />
      <SystemPage v-else-if="view==='system'&&role==='TEACHER'" />
      </div>
      </Transition>
    </div></a-layout-content>

    <FileReviewDrawer
      ref="fileReviewDrawer"
      :open="filePreview.open"
      :files="filePreview.files"
      :initial-index="filePreview.index"
      :submission-version-id="selectedSubmission?.submission_version_id||''"
      :owner="selectedSubmission?.owner||''"
      :assignment-title="filePreview.assignmentTitle||selectedAssignment?.title||selectedCampaign?.assignment_title||reviewTask?.assignment?.title||''"
      :editable="!filePreview.readonly&&(filePreview.mode==='TEACHER'&&role==='TEACHER'||filePreview.mode==='PEER'&&role==='STUDENT'&&!filePreview.initialFeedback)&&Boolean(selectedSubmission)"
      :mode="filePreview.mode"
      :targets="filePreview.targets"
      :target-index="filePreview.targetIndex"
      :initial-feedback="filePreview.initialFeedback"
      :peer-feedback-enabled="filePreview.mode==='TEACHER'&&Boolean(selectedSubmission?.peer_feedbacks?.length)"
      :peer-grade="filePreview.mode==='TEACHER' ? selectedSubmission?.peer_grade||'' : ''"
      :peer-feedbacks="filePreview.mode==='TEACHER' ? selectedSubmission?.peer_feedbacks||[] : []"
      @close="closeFilePreview"
      @feedback-published="handleFeedbackPublished"
      @clear-feedback="clearTeacherGrade"
      @target-change="changeReviewTarget"
      @external-target="handleExternalReviewTarget"
    />

    <a-modal v-model:open="noticesOpen" title="站内通知" :footer="null" width="520px" centered><div class="notification-toolbar"><span>{{notifications.filter(x=>!x.read).length ? `${notifications.filter(x=>!x.read).length} 条未读消息` : '消息已全部阅读'}}</span><a-button v-if="notifications.some(x=>!x.read)" type="link" @click="readAll">全部标为已读</a-button></div><a-empty v-if="!notifications.length" description="暂无通知"/><div v-else class="notification-list"><div v-for="item in notifications" :key="item.id" class="notification-item" :class="{unread:!item.read,actionable:item.link}" @click="openNotification(item)"><span class="notification-dot"/><div><strong>{{item.title}}</strong><span>{{formatTime(item.created_at)}}</span></div><RightOutlined v-if="item.link" class="notification-link-icon"/></div></div></a-modal>

    <a-modal v-model:open="modals.class" :title="classForm.id?'编辑教学班':'创建教学班'" ok-text="保存" @ok="saveClass"><a-form layout="vertical"><a-form-item label="课程"><a-input value="软件工程" disabled/></a-form-item><a-form-item label="学期" required><a-input v-model:value="classForm.semester" placeholder="例如：2025-2026-1"/></a-form-item><a-form-item label="班级名称" required><a-input v-model:value="classForm.name" placeholder="例如：24计算机1"/></a-form-item><a-form-item label="组队截止时间"><a-input v-model:value="classForm.team_deadline" type="datetime-local"/></a-form-item><a-form-item label="选题可见性"><a-switch v-model:checked="classForm.topic_public" checked-children="公开" un-checked-children="仅本组"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.import" title="导入学生名单" :footer="null" @cancel="closeImport"><a-steps :current="importState.step" size="small" :items="[{title:'上传名单'},{title:'预览校验'},{title:'确认导入'}]"/><a-upload-dragger v-if="!importState.result" :before-upload="chooseRoster" :show-upload-list="true" :max-count="1" accept=".csv,.xlsx"><p class="ant-upload-drag-icon"><UploadOutlined/></p><p>选择 XLSX 或 CSV 名单</p><p class="ant-upload-hint">必填列：学号、姓名</p></a-upload-dragger><a-table v-if="importState.preview" :data-source="importState.preview.rows" size="small" row-key="row" :pagination="{pageSize:5}"><a-table-column title="行" data-index="row"/><a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="name"/><a-table-column title="结果" data-index="reason"/></a-table><a-result v-if="importState.result" status="success" title="名单导入完成" :sub-title="`新建 ${importState.result.created} 个账号，加入 ${importState.result.joined} 名学生，跳过 ${importState.result.skipped} 行`"/><div class="modal-actions"><a-button @click="closeImport">{{importState.result?'关闭':'取消'}}</a-button><a-button v-if="!importState.preview" type="primary" :loading="importState.loading" @click="previewRoster">校验名单</a-button><a-button v-else-if="!importState.result" type="primary" :loading="importState.loading" @click="confirmRoster">确认导入</a-button><a-button v-else :href="`/api/v1/classes/${classId}/members/import/${importState.preview.batch_id}/result.csv`"><DownloadOutlined/> 下载结果</a-button></div></a-modal>
    <a-modal v-model:open="modals.member" :title="memberForm.id?'编辑成员':'添加成员'" :confirm-loading="memberSaving" ok-text="保存" @ok="saveMember"><a-form layout="vertical"><a-form-item label="学号" required><a-input v-model:value="memberForm.student_no" :disabled="Boolean(memberForm.id)" maxlength="32"/></a-form-item><a-form-item label="姓名" required><a-input v-model:value="memberForm.name" maxlength="80"/></a-form-item></a-form></a-modal>
    <StudentPortfolioDrawer :student="memberDetail" :class-id="classId" :writable="session.context?.current_class?.status==='ACTIVE'" @close="memberDetail=null" @saved="loadView" @reset-password="resetMemberPassword" @remove="removeClassMember" @preview="openPortfolioFilePreview"/>
    <a-modal v-model:open="modals.team" title="创建小组" @ok="createTeam"><a-form layout="vertical"><a-form-item label="小组名称" required><a-input v-model:value="teamForm.name"/></a-form-item><a-checkbox v-model:checked="teamForm.open_recruitment">允许其他成员申请加入</a-checkbox></a-form></a-modal>
<a-drawer :open="Boolean(selectedTeam)" :title="selectedTeam?.name" :width="role==='TEACHER'?'min(680px, 100vw)':'min(520px, 100vw)'" :get-container="false" :root-style="{position:'fixed'}" placement="right" @close="closeTeamDrawer"><template #extra><a-button class="team-export-button" v-if="role==='TEACHER'&&selectedTeam" :loading="exportingTeamIds.has(selectedTeam.id)" @click="downloadTeamCoursework(selectedTeam)"><DownloadOutlined/> 导出全部作业与成绩</a-button></template><template v-if="selectedTeam"><p>组长：{{selectedTeam.leader_name}} · {{selectedTeam.member_count}} 人</p><a-list :data-source="selectedTeam.members||[]"><template #renderItem="{item}"><a-list-item>{{item.name}}（{{item.student_no}}）<a-space><a-tag>{{roleLabel(item.role)}}</a-tag><a-button v-if="selectedTeam.is_leader&&item.role!=='LEADER'" type="link" @click="transferLeader(item.id)">移交组长</a-button></a-space></a-list-item></template></a-list><template v-if="role==='TEACHER'"><a-divider/><div class="team-drawer-topic"><span>选题</span><strong>{{selectedTeam.topic?.name||'暂未提交选题'}}</strong><p>{{selectedTeam.topic?.description||'暂无选题说明'}}</p></div><a-divider/><div class="team-drawer-section-title"><strong>近期小组作业</strong><span>最近 {{selectedTeamAssignments.length}} 次</span></div><a-skeleton v-if="teamDrawerLoading" active :paragraph="{rows:4}"/><a-empty v-else-if="!selectedTeamAssignments.length" description="暂无小组作业"/><div v-else class="team-assignment-history"><TeamAssignmentChart :assignments="selectedTeamAssignments"/><div v-for="assignment in selectedTeamAssignments" :key="assignment.id" class="team-assignment-item"><div><strong>{{assignment.title}}</strong><span>截止 {{formatTime(assignment.due_at)}}</span></div><div class="team-assignment-result"><a-tag :color="assignment.submission.status==='SUBMITTED'?'green':'default'">{{statusLabel(assignment.submission.status)}}</a-tag><a-tag v-if="assignment.submission.is_late" color="red">迟交</a-tag><span v-if="assignment.submission.status==='SUBMITTED'">{{formatTime(assignment.submission.submitted_at)}} · {{assignment.submission.files?.length||0}} 个附件</span></div></div></div></template><template v-if="selectedTeam.is_leader"><a-divider/><a-space-compact block><a-select v-model:value="inviteTarget" placeholder="选择未入组学生" style="width:100%" :options="members.filter(x=>!x.team).map(x=>({value:x.id,label:`${x.name}（${x.student_no}）`}))"/><a-button type="primary" :disabled="!inviteTarget" @click="inviteMember">邀请</a-button></a-space-compact><a-divider/><a-form layout="vertical"><a-form-item label="选题名称"><a-input v-model:value="topicForm.name"/></a-form-item><a-form-item><template #label><span class="topic-description-label">选题说明<a-tooltip overlay-class-name="topic-guidance-tooltip"><template #title>请说明项目面向谁、当前业务如何运作、存在什么具体痛点和关键异常；写明已经可以访谈的真实人员、与其关系及联系渠道，并概括准备纳入系统的核心后台流程。避免只写“提高效率、实现信息化”等空泛表述。选题应面向运营侧或后台流程，具有真实业务约束，并能延续到后续需求、设计、开发与测试。</template><QuestionCircleOutlined class="topic-help-icon" tabindex="0" aria-label="查看选题说明填写要求"/></a-tooltip></span></template><a-textarea v-model:value="topicForm.description" :rows="3"/></a-form-item><a-space><a-button type="primary" @click="saveTopic">提交选题审核</a-button><a-button danger @click="disbandTeam">解散小组</a-button></a-space></a-form></template><a-button v-else-if="role==='STUDENT'&&selectedTeam.id===session.context?.team_membership?.team_id" danger @click="leaveTeam">退出小组</a-button></template></a-drawer>
    <a-modal v-model:open="modals.assignment" :title="assignmentForm.id ? '编辑作业' : '新建作业'" :footer="null" width="720px">
      <a-form layout="vertical">
        <a-form-item v-if="!assignmentForm.id" label="教学班" required><a-select v-model:value="assignmentForm.class_ids" mode="multiple" placeholder="选择一个或多个教学班" :options="classOptions"/></a-form-item>
        <a-form-item label="标题" required><a-input v-model:value="assignmentForm.title"/></a-form-item>
        <a-form-item label="提交类型" :help="assignmentForm.has_submissions ? '已有提交，不能修改提交类型' : ''"><a-segmented v-model:value="assignmentForm.submitter_type" :disabled="assignmentForm.has_submissions||assignmentForm.auto_review_enabled" :options="[{label:'个人作业',value:'INDIVIDUAL'},{label:'小组作业',value:'TEAM'}]"/></a-form-item>
        <a-form-item label="开始时间"><a-input v-model:value="assignmentForm.starts_at" type="datetime-local"/></a-form-item>
        <a-form-item label="截止时间" required><a-input v-model:value="assignmentForm.due_at" type="datetime-local"/></a-form-item>
        <a-form-item label="说明" required><div class="editor-shell"><div v-if="descriptionEditor" class="editor-toolbar"><a-tooltip title="二级标题"><a-button size="small" :type="descriptionEditor.isActive('heading',{level:2})?'primary':'default'" @click="descriptionEditor.chain().focus().toggleHeading({level:2}).run()">H2</a-button></a-tooltip><a-tooltip title="粗体"><a-button size="small" :type="descriptionEditor.isActive('bold')?'primary':'default'" @click="descriptionEditor.chain().focus().toggleBold().run()"><BoldOutlined/></a-button></a-tooltip><a-tooltip title="无序列表"><a-button size="small" @click="descriptionEditor.chain().focus().toggleBulletList().run()"><UnorderedListOutlined/></a-button></a-tooltip><a-tooltip title="有序列表"><a-button size="small" @click="descriptionEditor.chain().focus().toggleOrderedList().run()"><OrderedListOutlined/></a-button></a-tooltip><a-tooltip title="链接"><a-button size="small" @click="setDescriptionLink"><LinkOutlined/></a-button></a-tooltip><a-tooltip title="代码块"><a-button size="small" @click="descriptionEditor.chain().focus().toggleCodeBlock().run()"><CodeOutlined/></a-button></a-tooltip></div><EditorContent :editor="descriptionEditor"/></div></a-form-item>
        <a-form-item label="作业附件"><AssignmentMaterials v-if="assignmentForm.id&&assignmentAttachments.length" :files="assignmentAttachments" can-delete :deleting="deletingMaterials" @preview="openFilePreview" @delete="deleteDraft" @delete-selected="deleteSelectedMaterials"/><a-upload :before-upload="queueAssignmentAttachment" :show-upload-list="false" multiple accept=".md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.pptx,.xlsx,.zip,.rar,.7z"><a-button><UploadOutlined/> 选择附件</a-button></a-upload><div v-for="(file,index) in pendingAssignmentFiles" :key="file.uid||`${file.name}-${index}`" class="uploaded-file"><span>{{file.name}}</span><a-button danger type="link" @click="removePendingAssignmentAttachment(index)">移除</a-button></div></a-form-item>
        <a-checkbox v-model:checked="assignmentForm.allow_late">允许迟交并标记</a-checkbox>
        <div class="modal-actions"><a-button @click="modals.assignment=false">取消</a-button><a-button @click="createAssignment(false)">{{assignmentForm.id?'保存修改':'保存草稿'}}</a-button><a-button type="primary" @click="createAssignment(true)">{{assignmentForm.id?'保存并再次发布':'发布'}}</a-button></div>
      </a-form>
    </a-modal>
    <a-modal v-model:open="modals.topicDecision" title="驳回选题" ok-text="确认驳回" @ok="rejectTopic"><a-form layout="vertical"><a-form-item label="驳回原因" required><a-textarea v-model:value="topicDecisionForm.reason" :rows="3" placeholder="请说明需要修改的内容"/></a-form-item></a-form></a-modal>
    <a-modal v-model:open="modals.password" title="修改密码" @ok="changePassword"><a-form layout="vertical"><a-form-item label="当前密码"><a-input-password v-model:value="passwordForm.current_password"/></a-form-item><a-form-item label="新密码"><a-input-password v-model:value="passwordForm.new_password"/></a-form-item></a-form></a-modal>
  </a-layout>
</template>
