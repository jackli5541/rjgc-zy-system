<script setup>
import { FormOutlined } from '@ant-design/icons-vue'
import { reactive, ref, watch } from 'vue'
import { useShellContext } from '../../shellContext'
const { campaigns, formatTime, openCampaign } = useShellContext()

const selectedReviewees = reactive({})
const openingAssignmentId = ref('')

watch(campaigns, items => {
  for (const item of items) {
    const current = selectedReviewees[item.assignment_id]
    if (item.candidates.some(candidate => candidate.user_id === current)) continue
    selectedReviewees[item.assignment_id] = (item.candidates.find(candidate => !candidate.reviewed) || item.candidates[0])?.user_id
  }
}, { immediate: true })

function selectedCandidate(item) {
  return item.candidates.find(candidate => candidate.user_id === selectedReviewees[item.assignment_id])
}

async function startReview(item) {
  const userId = selectedReviewees[item.assignment_id]
  if (!userId) return
  openingAssignmentId.value = item.assignment_id
  try { await openCampaign(item, userId) }
  finally { openingAssignmentId.value = '' }
}
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">组内作品互评</div><h1>作品互评</h1><p>选择本组已提交作业的成员，按 A–E 五档进行评价。</p></div></div>
  <a-empty v-if="!campaigns.length" description="暂无可评价的组员提交"/>
  <a-card v-for="item in campaigns" :key="item.assignment_id" class="assignment-row peer-review-row" :bordered="false">
    <div class="assignment-icon cyan"><FormOutlined/></div>
    <div class="assignment-main">
      <div class="assignment-heading"><h3>{{item.assignment_title}}</h3><a-tag v-if="item.pending_count===0" color="green">当前已完成</a-tag></div>
      <p>本组已有 {{item.available_count}} 人提交，可自由选择评价对象</p>
      <div class="assignment-meta"><span>仅限组内互评</span><span>作业截止 {{formatTime(item.due_at)}}</span></div>
    </div>
    <div class="assignment-end peer-review-entry">
      <strong>{{item.pending_count ? `待评价 ${item.pending_count} 人` : '可更新评价'}}</strong>
      <div class="peer-review-actions">
        <a-select
          v-model:value="selectedReviewees[item.assignment_id]"
          :options="item.candidates.map(candidate=>({value:candidate.user_id,label:`${candidate.name}（${candidate.student_no}）${candidate.reviewed?' · 已评价':''}`}))"
          aria-label="选择评价对象"
        />
        <a-button type="primary" :loading="openingAssignmentId===item.assignment_id" @click="startReview(item)">
          {{selectedCandidate(item)?.reviewed?'更新评价':'开始评价'}}
        </a-button>
      </div>
    </div>
  </a-card>
</template>
