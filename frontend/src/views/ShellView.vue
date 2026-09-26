<script setup>
import { computed, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ApartmentOutlined, BookOutlined, CalendarOutlined, ControlOutlined, DashboardOutlined, FileTextOutlined, FolderOpenOutlined, FormOutlined, SettingOutlined, TeamOutlined, TrophyOutlined } from '@ant-design/icons-vue'
import { api, apiClientId } from '../api'
import ShellHeader from '../shared/components/ShellHeader.vue'
import AssignmentsPage from '../modules/assignments/pages/AssignmentsPage.vue'
import CapstonePage from '../modules/capstone/pages/CapstonePage.vue'
import StudentCapstonePage from '../modules/capstone/pages/StudentCapstonePage.vue'
import ClassDetailPage from '../modules/members/pages/ClassDetailPage.vue'
import ClassesPage from '../modules/members/pages/ClassesPage.vue'
import GradesPage from '../modules/grades/pages/GradesPage.vue'
import OverviewPage from '../modules/overview/pages/OverviewPage.vue'
import ReviewDetailPage from '../modules/assignments/pages/ReviewDetailPage.vue'
import ReviewsPage from '../modules/assignments/pages/ReviewsPage.vue'
import RoleMenuPage from '../modules/system/pages/RoleMenuPage.vue'
import SystemPage from '../modules/system/pages/SystemPage.vue'
import TeachingMaterialsPage from '../modules/materials/pages/TeachingMaterialsPage.vue'
import AttendancePage from '../modules/attendance/pages/AttendancePage.vue'
import StudentAttendanceModal from '../modules/attendance/components/StudentAttendanceModal.vue'
import TeamsPage from '../modules/members/pages/TeamsPage.vue'
import AssignmentDetailDrawer from '../modules/assignments/components/AssignmentDetailDrawer.vue'
import AssignmentFormModal from '../modules/assignments/components/AssignmentFormModal.vue'
import AssignmentReviewDrawer from '../modules/assignments/components/AssignmentReviewDrawer.vue'
import MemberModals from '../modules/members/components/MemberModals.vue'
import TeamDrawer from '../modules/members/components/TeamDrawer.vue'
import SystemModals from '../modules/system/components/SystemModals.vue'
import { useLabels } from '../shared/composables/useLabels'
import { useDashboard } from '../modules/overview/composables/useDashboard'
import { useClasses } from '../modules/members/composables/useClasses'
import { useMembers } from '../modules/members/composables/useMembers'
import { useRoster } from '../modules/members/composables/useRoster'
import { useTeams } from '../modules/members/composables/useTeams'
import { useAssignments } from '../modules/assignments/composables/useAssignments'
import { useAssignmentDetail } from '../modules/assignments/composables/useAssignmentDetail'
import { useAssignmentDrawer } from '../modules/assignments/composables/useAssignmentDrawer'
import { useFeedback } from '../modules/assignments/composables/useFeedback'
import { useReviews } from '../modules/assignments/composables/useReviews'
import { useGrades } from '../modules/grades/composables/useGrades'
import { useAttendance } from '../modules/attendance/composables/useAttendance'
import { useAudits } from '../modules/system/composables/useAudits'
import { useNotifications } from '../modules/system/composables/useNotifications'
import { useSessionStore } from '../stores/session'
import { shellContextKey } from '../shellContext'
import { useResizableDrawer } from '../useHorizontalResize'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const loadedViewKeys = reactive(new Set())
let loadGeneration = 0
const modals = reactive({ class: false, import: false, member: false, team: false, assignment: false, password: false, topicDecision: false })
const passwordForm = reactive({ current_password: '', new_password: '' })
let gateTimer
let clockTimer
let realtimeSource
let realtimeTimer
let safetyTimer
let realtimeDirty = false
const pendingRealtimeScopes = new Set()

const role = computed(() => session.user?.role)
const classId = computed(() => session.classId)
const view = computed(() => route.name === 'assignment-detail' ? 'assignment-detail' : route.name === 'review-detail' ? 'review-detail' : route.name === 'grade-detail' ? 'grade-detail' : route.name === 'class-detail' ? 'class-detail' : route.params.view || 'overview')
const detailId = computed(() => route.params.id)
const pageKey = computed(() => `${role.value || 'guest'}:${classId.value || 'none'}:${view.value}:${detailId.value || ''}`)
const surfaceKey = computed(() => role.value === 'TEACHER' && view.value === 'assignment-detail'
  ? `${role.value}:${classId.value || 'none'}:assignments:`
  : pageKey.value)
const initialLoading = computed(() => loading.value && !loadedViewKeys.has(pageKey.value))
const navView = computed(() => view.value === 'assignment-detail' ? 'assignments' : view.value === 'review-detail' ? 'reviews' : view.value === 'grade-detail' ? 'grades' : view.value === 'class-detail' ? 'classes' : view.value)
const menu = computed(() => {
  const visible = items => items.filter(item => session.isMenuEnabled(item[0]))
  if (role.value === 'TEACHER') return [...visible([
    ['overview', DashboardOutlined, '总览'], ['classes', BookOutlined, '教学班'], ['teams', TeamOutlined, '小组与选题'],
    ['assignments', FileTextOutlined, '作业管理'], ['capstone', ApartmentOutlined, '大作业管理'], ['materials', FolderOpenOutlined, '教学资料'], ['attendance', CalendarOutlined, '考勤管理'], ['grades', TrophyOutlined, '成绩与导出'], ['system', SettingOutlined, '系统与审计']
  ]), ['menu-permissions', ControlOutlined, '角色菜单']]
  if (session.teamGate) return [['teams', TeamOutlined, '加入小组']]
  return visible([['overview', DashboardOutlined, '总览'], ['teams', TeamOutlined, '我的小组'], ['assignments', FileTextOutlined, '我的作业'], ['reviews', FormOutlined, '作品互评'], ['capstone', ApartmentOutlined, '大作业'], ['grades', TrophyOutlined, '成绩与反馈'], ['materials', FolderOpenOutlined, '教学资料']])
})

// 各业务模块的状态与动作都挂在 ctx 上，模块之间只通过 ctx 相互引用（延迟解析，不依赖创建顺序）。
const ctx = {
  session, route, router, loading, loadedViewKeys, modals, passwordForm,
  role, classId, view, detailId, pageKey, surfaceKey, initialLoading, navView, menu,
  action, loadView, navigate, logout, changePassword,
}

Object.assign(
  ctx,
  useLabels(ctx),
  useNotifications(ctx),
  useAudits(ctx),
  useClasses(ctx),
  useRoster(ctx),
  useMembers(ctx),
  useTeams(ctx),
  useAssignments(ctx),
  useAssignmentDrawer(ctx),
  useAssignmentDetail(ctx),
  useReviews(ctx),
  useFeedback(ctx),
  useGrades(ctx),
  useAttendance(ctx),
  useDashboard(ctx),
)

const { width: assignmentDrawerWidth, resizing: assignmentDrawerResizing, startResize: startAssignmentDrawerResize } = useResizableDrawer({ initialWidth: () => Math.max(720, window.innerWidth * ctx.DRAWER_COLLAPSED_RATIO), minWidth: 720, storageKey: 'assignment-detail-drawer-width' })
const { width: teamDrawerWidth, resizing: teamDrawerResizing, startResize: startTeamDrawerResize } = useResizableDrawer({ initialWidth: () => Math.max(420, window.innerWidth * ctx.DRAWER_COLLAPSED_RATIO), minWidth: 420, storageKey: 'team-portfolio-drawer-width' })
Object.assign(ctx, { assignmentDrawerWidth, assignmentDrawerResizing, startAssignmentDrawerResize, teamDrawerWidth, teamDrawerResizing, startTeamDrawerResize })
if (ctx.assignmentDrawerExpanded.value) assignmentDrawerWidth.value = window.innerWidth

// 每个视图的取数逻辑放在对应模块的 composable 里，这里只做分发和竞态控制。
const viewLoaders = {
  overview: (...args) => ctx.loadOverviewView(...args),
  'class-detail': (...args) => ctx.loadClassDetailView(...args),
  teams: (...args) => ctx.loadTeamsView(...args),
  assignments: (...args) => ctx.loadAssignmentsView(...args),
  'assignment-detail': (...args) => ctx.loadAssignmentDetailView(...args),
  reviews: (...args) => ctx.loadReviewsView(...args),
  'review-detail': (...args) => ctx.loadReviewDetailView(...args),
  grades: (...args) => ctx.loadGradesView(...args),
  attendance: (...args) => ctx.loadAttendanceView(...args),
  system: (...args) => ctx.loadAuditsView(...args),
  'grade-detail': async () => {
    if (role.value !== 'TEACHER') { await router.replace('/grades'); return }
    await router.replace({ name: 'assignment-detail', params: { id: detailId.value }, query: { tab: 'grades' } })
  },
}

async function action(fn, success) {
  const originPath = route.fullPath
  const preserveTeacherDrawer = role.value === 'TEACHER' && view.value === 'assignment-detail'
  try {
    await fn()
    if (success) message.success(success)
    await Promise.all([originPath === route.fullPath ? loadView({ silent: preserveTeacherDrawer }) : Promise.resolve(), ctx.loadNotifications()])
  } catch (e) { message.error(e.message) }
}

async function loadView({ silent = false, background = false } = {}) {
  const generation = ++loadGeneration
  const requestedKey = pageKey.value
  const isCurrent = () => generation === loadGeneration && requestedKey === pageKey.value
  if (!silent) loading.value = true
  try {
    if (!classId.value) return
    const loader = viewLoaders[view.value]
    if (loader) await loader(isCurrent, { background })
  } catch (e) { if (!background) message.error(e.message) }
  finally {
    if (isCurrent()) {
      loadedViewKeys.add(requestedKey)
      loading.value = false
    }
  }
}

async function changePassword() { await action(async () => { await api('/auth/password', { method: 'POST', body: JSON.stringify(passwordForm) }); modals.password = false; Object.assign(passwordForm, { current_password: '', new_password: '' }) }, '密码已更新') }

async function logout() { try { await session.logout() } catch (_) {} finally { await router.replace('/login') } }

function navigate(target) { return router.push(target) }

async function pollGate() {
  if (!session.teamGate) return
  const before = session.teamGate
  await session.refreshContext()
  if (before && !session.teamGate) { message.success('已加入小组'); clearInterval(gateTimer); await router.replace(session.landingPath) }
}

function currentViewUses(scopes) {
  if (scopes.includes('current_view')) return true
  const needed = {
    overview: ['dashboard', 'assignments', 'submissions', 'reviews', 'grades', 'teams'],
    classes: ['classes'],
    'class-detail': ['classes', 'members'],
    teams: ['teams', 'members'],
    assignments: ['assignments', 'submissions'],
    'assignment-detail': ['assignments', 'submissions', 'reviews', 'grades', 'teams'],
    reviews: ['reviews', 'submissions'],
    'review-detail': ['reviews', 'submissions'],
    capstone: [],
    grades: ['grades'],
    attendance: ['attendance'],
    materials: [],
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
    scopes.includes('notifications') || scopes.includes('current_view') ? ctx.loadNotifications() : Promise.resolve(),
    scopes.includes('menu_permissions') ? session.refreshMenuPermissions() : Promise.resolve()
  ])
  if (scopes.includes('menu_permissions') && view.value !== 'menu-permissions' && !session.teamGate && !session.isMenuEnabled(navView.value)) await router.replace(session.landingPath)
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
    if ((payload.scopes || []).includes('workspace')) {
      window.dispatchEvent(new CustomEvent('workspace-changed', { detail: { assignmentId: payload.assignment_id, workspaceId: payload.workspace_id, payload } }))
      return
    }
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
  ctx.assignmentDetailTab.value = allowedTabs.includes(tab) ? tab : 'details'
})

watch(() => route.path, () => { ctx.memberDetail.value = null; if (view.value !== 'assignment-detail') ctx.openedSubmissionPreview.value = '' })

watch(() => session.teamGate, required => { clearInterval(gateTimer); gateTimer = required ? setInterval(pollGate, 10000) : undefined })

watch(classId, () => { ctx.memberDetail.value = null; connectRealtime() })

watch(ctx.assignmentDrawerExpanded, value => localStorage.setItem(ctx.DRAWER_EXPANDED_STORAGE_KEY, String(value)))

onMounted(async () => {
  await Promise.all([loadView(), ctx.loadNotifications()])
  if (session.teamGate) gateTimer = setInterval(pollGate, 10000)
  clockTimer = setInterval(() => { ctx.currentTime.value = Date.now() }, 30000)
  window.addEventListener('focus', pollGate)
  window.addEventListener('resize', ctx.syncAssignmentDrawerToViewport)
  document.addEventListener('visibilitychange', handleVisibilitySync)
  connectRealtime(); startSafetyRefresh()
})

onBeforeUnmount(() => {
  clearInterval(gateTimer); clearInterval(clockTimer); clearInterval(safetyTimer); clearTimeout(realtimeTimer); clearTimeout(ctx.assignmentDrawerAnimationTimer)
  realtimeSource?.close()
  window.removeEventListener('focus', pollGate)
  window.removeEventListener('resize', ctx.syncAssignmentDrawerToViewport)
  document.removeEventListener('visibilitychange', handleVisibilitySync)
  ctx.closeFilePreview()
})

provide(shellContextKey, ctx)

const { selectedAssignment, selectedCampaign } = ctx
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

      <ClassDetailPage v-else-if="view==='class-detail'&&role==='TEACHER'" />

      <TeamsPage v-else-if="view==='teams'" />

      <AssignmentsPage v-else-if="view==='assignments'||(view==='assignment-detail'&&role==='TEACHER')" />

      <AssignmentDetailDrawer v-if="view==='assignment-detail'&&selectedAssignment" />

      <ReviewsPage v-else-if="view==='reviews'" />
      <ReviewDetailPage v-else-if="view==='review-detail'&&selectedCampaign" />

      <CapstonePage v-else-if="view==='capstone'&&role==='TEACHER'" />
      <StudentCapstonePage v-else-if="view==='capstone'&&role==='STUDENT'" />
      <GradesPage v-else-if="view==='grades'" />
      <AttendancePage v-else-if="view==='attendance'&&role==='TEACHER'" />
      <TeachingMaterialsPage v-else-if="view==='materials'" />
      <SystemPage v-else-if="view==='system'&&role==='TEACHER'" />
      <RoleMenuPage v-else-if="view==='menu-permissions'&&role==='TEACHER'" />
      </div>
      </Transition>
    </div></a-layout-content>

    <AssignmentReviewDrawer />
    <SystemModals />
    <StudentAttendanceModal v-if="role==='STUDENT'" />
    <MemberModals />
    <TeamDrawer />
    <AssignmentFormModal />
  </a-layout>
</template>
