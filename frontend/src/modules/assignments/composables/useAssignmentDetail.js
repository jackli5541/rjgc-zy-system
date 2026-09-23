import { api } from '../../../api'
import { Modal, message } from 'ant-design-vue'
import { computed, nextTick, ref } from 'vue'

export function useAssignmentDetail(ctx) {
  const selectedAssignment = ref(null)

  const selectedSubmission = ref(null)

  const openedSubmissionPreview = ref('')

  const assignmentDetailTab = ref('details')

  const boardFilter = ref('ALL')

  const boardQuery = ref('')

  const boardTeamFilter = ref('ALL')

  const submissionBoardPane = ref(null)

  const onlineWorkspace = ref(null)

  const onlineWorkspaceData = ref(null)

  const boardTeamOptions = computed(() => {
    const options = new Map()
    for (const item of selectedAssignment.value?.board || []) {
      if (item.team_id && item.team_name) options.set(item.team_id, item.team_name)
    }
    return [
      { value: 'ALL', label: '全部小组' },
      { value: 'NONE', label: '未分组' },
      ...[...options].map(([value, label]) => ({ value, label }))
    ]
  })

  const filteredBoard = computed(() => (selectedAssignment.value?.board || []).filter(item => {
    const q = boardQuery.value.trim().toLocaleLowerCase()
    const matchesQuery = !q || `${item.owner || ''} ${item.student_no || ''}`.toLocaleLowerCase().includes(q)
    const matchesTeam = boardTeamFilter.value === 'ALL' || (boardTeamFilter.value === 'NONE' ? !item.team_id : item.team_id === boardTeamFilter.value)
    const matchesStatus = boardFilter.value === 'ALL'
      || (boardFilter.value === 'LATE' && item.is_late)
      || (boardFilter.value === 'REVIEWED' && item.status === 'SUBMITTED' && Boolean(item.teacher_grade))
      || (boardFilter.value === 'PENDING_REVIEW' && item.status === 'SUBMITTED' && !item.teacher_grade)
      || boardFilter.value === item.status
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

  const assignmentSubmitted = computed(() => selectedAssignment.value?.submission?.status === 'SUBMITTED')

  const assignmentBeforeDue = computed(() => Boolean(selectedAssignment.value && new Date(selectedAssignment.value.due_at) > new Date()))

  const assignmentIsUpdate = computed(() => assignmentSubmitted.value && assignmentBeforeDue.value)

  const submissionFinalGrade = computed(() => selectedAssignment.value?.submission?.final_grade || null)

  const submissionUpdateAllowed = computed(() => {
    if (!assignmentSubmitted.value) return true
    return ['C', 'D', 'E'].includes(submissionFinalGrade.value)
  })

  const canManageTeamSubmission = computed(() => {
    if (selectedAssignment.value?.submitter_type !== 'TEAM') return true
    return ctx.session.context?.team_membership?.role === 'LEADER' && ctx.currentTeam.value?.is_leader === true
  })

  const canSubmitAssignment = computed(() => {
    const assignment = selectedAssignment.value
    if (!assignment) return false
    if (assignment.status !== 'PUBLISHED') return false
    if (!canManageTeamSubmission.value) return false
    if (!submissionUpdateAllowed.value) return !assignmentSubmitted.value
    if (assignmentSubmitted.value && submissionUpdateAllowed.value) return true
    return new Date(assignment.due_at) > new Date() || (!assignmentSubmitted.value && assignment.allow_late)
  })

  const canEditAssignment = computed(() => {
    const assignment = selectedAssignment.value
    if (!assignment || assignment.status !== 'PUBLISHED') return false
    return new Date(assignment.due_at) > new Date() || assignment.allow_late
  })

  const reviewConfigEditable = computed(() => Boolean(selectedAssignment.value && selectedAssignment.value.status !== 'CLOSED' && new Date(selectedAssignment.value.due_at) > new Date() && !ctx.selectedCampaign.value))

  async function focusSubmissionStatus(filter) {
    boardFilter.value = filter
    boardQuery.value = ''
    boardTeamFilter.value = 'ALL'
    await nextTick()
    const pane = submissionBoardPane.value
    if (!pane) return
    const target = pane.querySelector('.submission-group tbody tr') || pane
    const top = target.getBoundingClientRect().top + window.scrollY - 24
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  }

  async function loadAssignmentDetail(item, isStillCurrent = () => true, { preserveUi = false } = {}) {
    selectedAssignment.value = item
    if (!preserveUi) {
      selectedSubmission.value = null; ctx.selectedCampaign.value = null; boardFilter.value = 'ALL'; boardTeamFilter.value = 'ALL'; boardQuery.value = ''
    }
    if (ctx.role.value === 'STUDENT') {
      const [files, submission] = await Promise.all([api(`/assignments/${item.id}/files`), api(`/assignments/${item.id}/submission`)])
      if (!isStillCurrent()) return
      ctx.assignmentAttachments.value = files.attachments; ctx.reviewCriteriaFiles.value = files.review_criteria || []; ctx.draftFiles.value = files.drafts
      item.submission = submission
    }
    else {
      const [files, boardData] = await Promise.all([api(`/assignments/${item.id}/files`), api(`/assignments/${item.id}/submissions`)])
      if (!isStillCurrent()) return
      ctx.assignmentAttachments.value = files.attachments; ctx.reviewCriteriaFiles.value = files.review_criteria || []; ctx.draftFiles.value = files.drafts
      item.board = boardData.items
      if (preserveUi && ctx.filePreview.open && selectedSubmission.value) {
        const refreshed = boardData.items.find(record => record.user_id && record.user_id === selectedSubmission.value.user_id)
        if (refreshed) requestAnimationFrame(() => ctx.fileReviewDrawer.value?.handleExternalSubmission?.(refreshed))
      }
    }
  }

  function changeAssignmentDetailTab(key) {
    assignmentDetailTab.value = key
    ctx.router.replace({ name: 'assignment-detail', params: { id: selectedAssignment.value.id }, query: key === 'details' ? {} : { tab: key } })
  }

  async function openAssignment(item, tab = 'details') {
    selectedAssignment.value = item
    assignmentDetailTab.value = tab
    const query = tab === 'details' ? {} : { tab }
    await ctx.router.push({ name: 'assignment-detail', params: { id: item.id }, query })
  }

  async function closeAssignmentDrawer() {
    await ctx.router.push('/assignments')
  }

  async function submitAssignment() {
    if (!canManageTeamSubmission.value) return message.warning('小组作业仅组长可以正式提交')
    if (!await onlineWorkspace.value?.save()) return message.warning('请先解决文档保存问题')
    const updating = assignmentIsUpdate.value
    const count = onlineWorkspaceData.value?.documents?.length || 0
    const warning = updating
      ? '提交更新后，在互评完成或教师评分前不能再次修改。'
      : `将提交在线工作区中的 ${count} 份 Markdown 文档。提交后，在互评完成或教师评分前不能修改或重新提交。`
    Modal.confirm({ title: updating ? '确认更新提交？' : '确认正式提交？', content: warning, okText: updating ? '确认更新' : '确认提交', cancelText: '继续检查', onOk: async () => ctx.action(() => api(`/assignments/${selectedAssignment.value.id}/submission`, { method: 'POST', headers: { 'Idempotency-Key': ctx.idempotencyKey() }, body: JSON.stringify({}) }), updating ? '提交已更新' : '提交成功') })
  }

  function openSubmissionDetail(record) {
    const targets = (selectedAssignment.value?.board || []).filter(item => item.status === 'SUBMITTED' && item.files?.length)
    const targetIndex = Math.max(0, targets.findIndex(item => item.submission_version_id === record.submission_version_id))
    ctx.openAssessmentDrawer(record, { mode: 'TEACHER', targets, targetIndex })
  }

  function pendingTeacherReviewTargets(board = selectedAssignment.value?.board || []) {
    return board.filter(item => item.status === 'SUBMITTED' && item.files?.length && (!item.teacher_grade || item.grade_carried_forward))
  }

  async function continueGrading(item) {
    try {
      const board = await api(`/assignments/${item.id}/submissions`)
      const targets = pendingTeacherReviewTargets(board.items)
      if (!targets.length) return message.info('暂无待批改作业')
      await ctx.router.push({ name: 'assignment-detail', params: { id: item.id }, query: { tab: 'submission', grade_submission: targets[0].submission_version_id } })
    } catch (error) { message.error(error.message) }
  }

  function openStudentFeedback(record, peerFeedback = null) {
    const combined = !peerFeedback && record.teacher_grade && record.files?.length
    const submission = { ...record, owner: peerFeedback?.evaluator_name || record.assignment_title, peer_feedbacks: record.peer_feedbacks || [] }
    ctx.openAssessmentDrawer(submission, { mode: combined ? 'TEACHER' : peerFeedback ? 'PEER' : 'TEACHER', initialFeedback: peerFeedback })
  }

  function openStudentAssignment(item) {
    const grade = ctx.grades.value.find(record => record.assignment_id === item.id)
    const hasFeedback = grade && ((grade.teacher_grade && grade.files?.length) || grade.peer_feedbacks?.length)
    if (item.status === 'CLOSED' || new Date(item.due_at) <= new Date()) {
      if (hasFeedback) return openStudentFeedback(grade)
    }
    return openAssignment(item, 'details')
  }

  async function refreshSubmissionBoard() {
    const board = await api(`/assignments/${selectedAssignment.value.id}/submissions`)
    selectedAssignment.value.board = board.items
  }

  function openLatestSubmission() {
    const submission = ctx.dashboard.value?.summary?.latest_submission
    if (!submission) return
    return ctx.router.push({ name: 'assignment-detail', params: { id: submission.assignment_id }, query: { tab: 'submission', grade_submission: submission.submission_version_id } })
  }

  async function loadAssignmentDetailView(isCurrent, { background = false } = {}) {
      const assignmentData = await api(`/assignments?class_id=${ctx.classId.value}`)
      if (!isCurrent()) return
      ctx.assignments.value = assignmentData.items
      const assignment = ctx.assignments.value.find(item => item.id === ctx.detailId.value)
      if (!assignment) { message.error('作业不存在或无权查看'); await ctx.router.replace('/assignments') }
      else {
        const allowedTabs = ['details', 'submission']
        assignmentDetailTab.value = allowedTabs.includes(ctx.route.query.tab) ? ctx.route.query.tab : 'details'
        await loadAssignmentDetail(assignment, isCurrent, { preserveUi: background })
        const previewVersion = ctx.route.query.preview_submission
        const previewKey = `${assignment.id}:${previewVersion || ''}`
        if (previewVersion && isCurrent() && openedSubmissionPreview.value !== previewKey) {
          const record = assignment.board?.find(item => item.submission_version_id === previewVersion && item.status === 'SUBMITTED' && item.files?.length)
          openedSubmissionPreview.value = previewKey
          if (record) openSubmissionDetail(record)
          else message.warning('该提交暂无可预览文件')
        }
        const gradingVersion = ctx.route.query.grade_submission
        const gradingKey = `${assignment.id}:grading:${gradingVersion || ''}`
        if (gradingVersion && isCurrent() && openedSubmissionPreview.value !== gradingKey) {
          const targets = pendingTeacherReviewTargets(assignment.board)
          const record = targets.find(item => item.submission_version_id === gradingVersion)
          openedSubmissionPreview.value = gradingKey
          if (record) ctx.openAssessmentDrawer(record, { mode: 'TEACHER', targets, targetIndex: targets.indexOf(record), pendingOnly: true })
          else message.info('暂无待批改作业')
        }
      }
    
  }

  return { selectedAssignment, selectedSubmission, openedSubmissionPreview, assignmentDetailTab, boardFilter, boardQuery, boardTeamFilter, submissionBoardPane, onlineWorkspace, onlineWorkspaceData, boardTeamOptions, filteredBoard, groupedBoard, teacherSubmissionSummary, assignmentSubmitted, assignmentBeforeDue, assignmentIsUpdate, submissionFinalGrade, submissionUpdateAllowed, canManageTeamSubmission, canSubmitAssignment, canEditAssignment, reviewConfigEditable, focusSubmissionStatus, loadAssignmentDetail, changeAssignmentDetailTab, openAssignment, closeAssignmentDrawer, submitAssignment, openSubmissionDetail, pendingTeacherReviewTargets, continueGrading, openStudentFeedback, openStudentAssignment, refreshSubmissionBoard, openLatestSubmission, loadAssignmentDetailView }
}
