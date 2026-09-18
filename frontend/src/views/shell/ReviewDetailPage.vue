<script setup>
import { ArrowLeftOutlined, FileTextOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'
import AssignmentMaterials from '../../components/AssignmentMaterials.vue'
const { selectedCampaign, reviewTask, reviewForm, selectedReviewCandidate, formatTime, navigate, selectReviewCandidate, openFilePreview, openPeerReviewDrawer } = useShellContext()
</script>

<template>
  <div class="page-title detail-title"><div><div class="eyebrow">组内互评</div><h1>{{selectedCampaign.assignment_title}}</h1><div class="assignment-title-meta"><a-tag color="cyan">仅限本组</a-tag><span>{{reviewTask?.team?.name}}</span></div></div><a-button @click="navigate('/reviews')"><ArrowLeftOutlined/> 返回互评列表</a-button></div>
  <section class="assignment-workspace review-workspace">
    <section v-if="reviewTask?.attachments?.length" class="assignment-pane">
      <div class="assignment-pane-heading"><h2>作业资料</h2><span>{{reviewTask.attachments.length}} 个附件</span></div>
      <AssignmentMaterials :files="reviewTask.attachments" :assignment-id="reviewTask.assignment.id" @preview="openFilePreview"/>
    </section>
    <a-empty v-if="!reviewTask?.candidates.length" description="本组暂无其他成员提交作业"/>
    <template v-else>
      <section class="assignment-pane"><div class="assignment-pane-heading"><h2>选择评价对象</h2><span>{{reviewTask.candidates.length}} 人已提交</span></div><a-select :value="reviewForm.reviewee_id" style="width:100%" :options="reviewTask.candidates.map(item=>({value:item.user_id,label:`${item.name}（${item.student_no}）${item.review?' · 已评价':''}`}))" @change="selectReviewCandidate"/></section>
      <section v-if="selectedReviewCandidate" class="assignment-pane"><div class="assignment-pane-heading review-submission-heading"><a-space><span>提交于 {{formatTime(selectedReviewCandidate.submitted_at)}}</span><a-tag v-if="selectedReviewCandidate.review" color="green">已评价</a-tag></a-space></div><div class="assignment-file-list"><div v-for="file in selectedReviewCandidate.files" :key="file.id" class="assignment-file-row"><span class="assignment-file-icon"><FileTextOutlined/></span><button type="button" class="file-preview-link" @click="openPeerReviewDrawer(selectedReviewCandidate,file)">{{file.name}}</button></div></div><div class="submission-actions"><a-button type="primary" :disabled="!selectedReviewCandidate.files.length" @click="openPeerReviewDrawer(selectedReviewCandidate)">{{selectedReviewCandidate.review?'打开并更新评价':'开始评价'}}</a-button></div></section>
    </template>
  </section>
</template>
