import { api } from '../../../api'
import { message } from 'ant-design-vue'
import { computed, reactive, ref } from 'vue'

export function useReviews(ctx) {
  const campaigns = ref([])

  const selectedCampaign = ref(null)

  const reviewTask = ref(null)

  const reviewForm = reactive({ grade: undefined, comment: '', reviewee_id: '' })

  const selectedReviewCandidate = computed(() => reviewTask.value?.candidates?.find(item => item.user_id === reviewForm.reviewee_id) || null)

  const studentPendingReviews = computed(() => campaigns.value.reduce((total, item) => total + Number(item.pending_count || 0), 0))

  async function loadCampaignDetail(item, isStillCurrent = () => true, preferredUserId = '') {
    const task = await api(`/assignments/${item.assignment_id}/peer-review`)
    if (!isStillCurrent()) return
    selectedCampaign.value = item
    reviewTask.value = task
    const first = task.candidates.find(candidate => candidate.user_id === preferredUserId) || task.candidates[0]
    Object.assign(reviewForm, { reviewee_id: first?.user_id || '', grade: first?.review?.grade, comment: first?.review?.comment || '' })
  }

  async function openCampaign(item) {
    await ctx.router.push(`/reviews/${item.assignment_id}`)
  }

  function selectReviewCandidate(userId) {
    const candidate = reviewTask.value?.candidates?.find(item => item.user_id === userId)
    Object.assign(reviewForm, { reviewee_id: userId, grade: candidate?.review?.grade, comment: candidate?.review?.comment || '' })
  }

  async function submitReview() {
    if (!reviewForm.reviewee_id) return message.warning('请选择要评价的组员')
    if (!reviewForm.grade) return message.warning('请先选择作业等级')
    const updating = Boolean(selectedReviewCandidate.value?.review)
    await ctx.action(async () => { await api(`/assignments/${selectedCampaign.value.assignment_id}/peer-reviews`, { method: 'POST', body: JSON.stringify(reviewForm) }); await loadCampaignDetail(selectedCampaign.value) }, updating ? '评价已更新' : '评价已提交')
  }

  function openPeerReviewDrawer(candidate, file = candidate?.files?.[0]) {
    if (!candidate?.files?.length || !file) return message.warning('该组员没有可预览的提交文件')
    ctx.peerReviewExpanded.value = true
    const lockedByOther = Boolean(candidate.review && candidate.can_review === false)
    const submission = { ...candidate, owner: lockedByOther ? candidate.review.evaluator_name : candidate.name }
    const criteriaFiles = [...(reviewTask.value?.review_criteria || []), ...(reviewTask.value?.criteria_files || [])]
      .filter((item, index, files) => files.findIndex(file => file.id === item.id) === index)
    ctx.openAssessmentDrawer(submission, { mode: 'PEER', file, initialFeedback: lockedByOther ? candidate.review : null, readonly: lockedByOther, criteriaFiles, criteriaText: reviewTask.value?.assignment?.auto_review_criteria_text || '' })
  }

  async function loadReviewsView(isCurrent, { background = false } = {}) {
      if (ctx.role.value === 'TEACHER') { await ctx.router.replace('/assignments'); return }
      const campaignData = await api(`/peer-review-assignments?class_id=${ctx.classId.value}`)
      if (!isCurrent()) return
      campaigns.value = campaignData.items
    
  }

  async function loadReviewDetailView(isCurrent, { background = false } = {}) {
      if (ctx.role.value === 'TEACHER') { await ctx.router.replace('/assignments'); return }
      const campaignData = await api(`/peer-review-assignments?class_id=${ctx.classId.value}`)
      if (!isCurrent()) return
      campaigns.value = campaignData.items
      const assignment = campaigns.value.find(item => item.assignment_id === ctx.detailId.value)
      if (!assignment) { message.error('当前没有可互评的组员提交'); await ctx.router.replace('/reviews') }
      else await loadCampaignDetail(assignment, isCurrent)
    
  }

  return { campaigns, selectedCampaign, reviewTask, reviewForm, selectedReviewCandidate, studentPendingReviews, loadCampaignDetail, openCampaign, selectReviewCandidate, submitReview, openPeerReviewDrawer, loadReviewsView, loadReviewDetailView }
}
