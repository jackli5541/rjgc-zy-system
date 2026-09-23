import { api } from '../../../api'
import { message } from 'ant-design-vue'
import { reactive } from 'vue'

export function useFeedback(ctx) {
  const filePreview = reactive({ open: false, files: [], criteriaFiles: [], criteriaText: '', index: 0, mode: 'PREVIEW', targets: [], targetIndex: 0, initialFeedback: null, pendingOnly: false, readonly: false, assignmentTitle: '' })

  function openAssessmentDrawer(record, { mode, targets = [], targetIndex = 0, initialFeedback = null, file = record.files?.[0], pendingOnly = false, readonly = false, criteriaFiles = [], criteriaText = '' } = {}) {
    ctx.selectedSubmission.value = record
    filePreview.mode = mode
    filePreview.targets = targets
    filePreview.targetIndex = targetIndex
    filePreview.initialFeedback = initialFeedback
    filePreview.pendingOnly = pendingOnly
    filePreview.readonly = readonly
    filePreview.assignmentTitle = ''
    filePreview.files = [...(record.files || [])]
    filePreview.criteriaFiles = [...criteriaFiles]
    filePreview.criteriaText = criteriaText
    filePreview.index = Math.max(0, filePreview.files.findIndex(item => item.id === file?.id))
    filePreview.open = true
  }

  function changeReviewTarget(targetIndex) {
    const record = filePreview.targets[targetIndex]
    if (!record) return
    ctx.selectedSubmission.value = record
    filePreview.targetIndex = targetIndex
    filePreview.files = [...record.files]
    filePreview.index = 0
    filePreview.initialFeedback = null
  }

  function handleExternalReviewTarget(record) {
    ctx.selectedSubmission.value = record
    const targets = filePreview.pendingOnly ? ctx.pendingTeacherReviewTargets() : ctx.selectedAssignment.value?.board?.filter(item => item.status === 'SUBMITTED' && item.files?.length) || []
    const targetIndex = Math.max(0, targets.findIndex(item => item.submission_version_id === record.submission_version_id))
    Object.assign(filePreview, { targets, targetIndex, files: [...(record.files || [])], index: 0, initialFeedback: null })
  }

  async function handleFeedbackPublished(result) {
    if (ctx.selectedSubmission.value && result) Object.assign(ctx.selectedSubmission.value, result)
    if (ctx.role.value === 'TEACHER' && ctx.selectedAssignment.value) await ctx.refreshSubmissionBoard()
    if (filePreview.mode === 'PEER' && ctx.selectedCampaign.value) {
      const selectedUserId = ctx.selectedSubmission.value?.user_id
      await ctx.loadCampaignDetail(ctx.selectedCampaign.value, () => true, selectedUserId)
      const campaignData = await api(`/peer-review-assignments?class_id=${ctx.classId.value}`)
      ctx.campaigns.value = campaignData.items
      ctx.selectedCampaign.value = ctx.campaigns.value.find(item => item.assignment_id === ctx.selectedCampaign.value?.assignment_id) || ctx.selectedCampaign.value
    }
  }

  async function clearTeacherGrade() {
    try {
      const path = ctx.selectedAssignment.value.submitter_type === 'TEAM'
        ? `/submission-versions/${ctx.selectedSubmission.value.submission_version_id}/feedback`
        : `/assignments/${ctx.selectedAssignment.value.id}/submissions/${ctx.selectedSubmission.value.user_id}/grade`
      const result = await api(path, { method: 'DELETE' })
      Object.assign(ctx.selectedSubmission.value, result)
      await ctx.refreshSubmissionBoard()
      closeFilePreview()
      message.success(result.final_grade ? '已恢复由互评成绩决定' : '教师评分已清除，当前暂无互评成绩')
    } catch (error) { message.error(error.message) }
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
    const isTeamAssignment = Boolean(assignment.submission)
    const record = assignment.submission || assignment
    const submission = {
      owner: isTeamAssignment ? ctx.selectedTeam.value?.name || '' : ctx.memberDetail.value?.name || '',
      user_id: isTeamAssignment ? '' : ctx.memberDetail.value?.id || '',
      submission_version_id: record.submission_version_id,
      files: [...files],
      teacher_grade: record.teacher_grade,
      peer_grade: isTeamAssignment ? null : record.peer_grade,
      peer_feedbacks: isTeamAssignment ? [] : record.received_reviews || []
    }
    ctx.selectedSubmission.value = submission
    Object.assign(filePreview, { mode: 'TEACHER', targets: [], targetIndex: 0, initialFeedback: record.teacher_grade, pendingOnly: false, readonly: true, assignmentTitle: assignment.title, files: [...files], index: Math.max(0, files.findIndex(item => item.id === file.id)), open: true })
  }

  function closeFilePreview() {
    filePreview.open = false
    if (filePreview.mode !== 'PEER') ctx.fileReviewExpanded.value = false
    ctx.selectedSubmission.value = null
  }

  return { filePreview, openAssessmentDrawer, changeReviewTarget, handleExternalReviewTarget, handleFeedbackPublished, clearTeacherGrade, openFilePreview, openPortfolioFilePreview, closeFilePreview }
}
