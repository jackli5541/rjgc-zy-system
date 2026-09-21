<script setup>
import { computed, ref } from 'vue'
import { ArrowLeftOutlined, CheckCircleFilled, ClockCircleOutlined, DownOutlined, FileTextOutlined, InfoCircleOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'
import AssignmentMaterials from '../../components/AssignmentMaterials.vue'

const { selectedCampaign, reviewTask, reviewForm, selectedReviewCandidate, formatTime, navigate, selectReviewCandidate, openFilePreview, openPeerReviewDrawer } = useShellContext()
const showReference = ref(false)
const candidates = computed(() => reviewTask.value?.candidates || [])
const reviewedCount = computed(() => candidates.value.filter(item => item.review).length)
const pendingCount = computed(() => candidates.value.length - reviewedCount.value)
</script>

<template>
  <div class="page-title detail-title">
    <div>
      <div class="eyebrow">组内互评</div>
      <h1>{{ selectedCampaign.assignment_title }}</h1>
      <div class="assignment-title-meta"><a-tag color="cyan">仅限本组</a-tag><span>{{ reviewTask?.team?.name }}</span></div>
    </div>
    <a-button @click="navigate('/reviews')"><ArrowLeftOutlined /> 返回互评列表</a-button>
  </div>

  <section class="assignment-workspace review-workspace peer-review-workspace">
    <header class="peer-review-overview">
      <div class="peer-review-progress">
        <span class="peer-review-progress-label">互评进度</span>
        <strong class="peer-review-progress-value">{{ reviewedCount }}<small>/ {{ candidates.length }}</small></strong>
        <span class="peer-review-progress-copy">{{ pendingCount ? `还有 ${pendingCount} 人待评价` : '本组评价已完成' }}</span>
      </div>
      <div class="peer-review-context"><span>{{ reviewTask?.team?.name }}</span><span>{{ candidates.length }} 人已提交</span></div>
    </header>

    <section v-if="reviewTask?.attachments?.length" class="peer-review-reference">
      <button type="button" class="peer-review-reference-toggle" :aria-expanded="showReference" @click="showReference = !showReference">
        <span><InfoCircleOutlined /> 作业要求与参考资料 <small>{{ reviewTask.attachments.length }} 个附件</small></span>
        <DownOutlined :class="{ open: showReference }" />
      </button>
      <transition name="detail-fade">
        <div v-if="showReference" class="peer-review-reference-body">
          <AssignmentMaterials :files="reviewTask.attachments" :assignment-id="reviewTask.assignment.id" can-download @preview="openFilePreview" />
        </div>
      </transition>
    </section>

    <div v-if="!candidates.length" class="peer-review-empty">
      <a-empty description="本组暂时没有其他成员提交作业" />
    </div>
    <div v-else class="peer-review-layout">
      <aside class="peer-review-queue" aria-label="评价对象列表">
        <div class="peer-review-queue-heading"><div><strong>评价对象</strong><span>按提交情况选择</span></div><b>{{ candidates.length }}</b></div>
        <nav class="peer-review-candidate-list">
          <button v-for="candidate in candidates" :key="candidate.user_id" type="button" class="peer-review-candidate" :class="{ active: reviewForm.reviewee_id === candidate.user_id }" :aria-current="reviewForm.reviewee_id === candidate.user_id ? 'true' : undefined" @click="selectReviewCandidate(candidate.user_id)">
            <span class="peer-review-candidate-icon" :class="{ done: candidate.review }"><CheckCircleFilled v-if="candidate.review" /><ClockCircleOutlined v-else /></span>
            <span class="peer-review-candidate-main"><strong>{{ candidate.name }}</strong><small>{{ candidate.student_no }}</small><small>{{ candidate.files?.length || 0 }} 个文件 · {{ formatTime(candidate.submitted_at) }}</small><small v-if="candidate.review" class="peer-review-candidate-result">评价者：{{ candidate.review.evaluator_name }} · 等级 {{ candidate.review.grade }}</small></span>
            <span class="peer-review-candidate-status" :class="{ done: candidate.review }">{{ candidate.review ? candidate.review.grade : '待评价' }}</span>
          </button>
        </nav>
      </aside>

      <section v-if="selectedReviewCandidate" class="peer-review-submission">
        <header class="peer-review-submission-header">
          <div class="peer-review-submission-heading"><span class="eyebrow">当前被评作品</span><h2>{{ selectedReviewCandidate.name }}</h2><span>{{ selectedReviewCandidate.student_no }} · 提交于 {{ formatTime(selectedReviewCandidate.submitted_at) }}</span></div>
          <a-tag :color="selectedReviewCandidate.review ? 'green' : 'gold'">{{ selectedReviewCandidate.review ? `已评价 · ${selectedReviewCandidate.review.grade}` : '待评价' }}</a-tag>
        </header>
        <div class="peer-review-file-section">
          <div class="peer-review-file-heading"><strong>学生提交内容</strong><span>{{ selectedReviewCandidate.files?.length || 0 }} 个文件</span></div>
          <div v-if="selectedReviewCandidate.files?.length" class="assignment-file-list">
            <div v-for="file in selectedReviewCandidate.files" :key="file.id" class="assignment-file-row peer-review-file-row">
              <span class="assignment-file-icon"><FileTextOutlined /></span>
              <button type="button" class="file-preview-link" @click="openPeerReviewDrawer(selectedReviewCandidate, file)">{{ file.name }}</button>
            </div>
          </div>
          <a-empty v-else description="该提交没有可评价的文件" />
        </div>
        <div class="peer-review-actions">
          <span v-if="selectedReviewCandidate.review">评价者：{{ selectedReviewCandidate.review.evaluator_name }} · 等级 {{ selectedReviewCandidate.review.grade }}<template v-if="selectedReviewCandidate.can_edit"> · 可继续修改</template></span>
          <span v-else>尚未完成评价</span>
          <a-button type="primary" :disabled="!selectedReviewCandidate.files?.length || selectedReviewCandidate.can_review === false" @click="openPeerReviewDrawer(selectedReviewCandidate)">{{ selectedReviewCandidate.can_edit ? '修改评价' : selectedReviewCandidate.can_review === false ? '已由他人评价' : '开始评价' }}</a-button>
        </div>
      </section>
    </div>
  </section>
</template>
