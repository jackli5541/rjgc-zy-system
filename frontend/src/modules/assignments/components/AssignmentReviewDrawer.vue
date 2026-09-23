<script setup>
import FileReviewDrawer from './FileReviewDrawer.vue'
import { useShellContext } from '../../../shellContext'

const { changeReviewTarget, clearTeacherGrade, closeFilePreview, filePreview, fileReviewDrawer, fileReviewExpanded, gradingCriteriaFiles, handleExternalReviewTarget, handleFeedbackPublished, peerReviewExpanded, reviewTask, role, selectedAssignment, selectedCampaign, selectedSubmission, updateFileReviewExpanded } = useShellContext()
</script>

<template>
    <FileReviewDrawer
      ref="fileReviewDrawer"
      :open="filePreview.open"
      :files="filePreview.files"
      :initial-index="filePreview.index"
      :submission-version-id="selectedSubmission?.submission_version_id||''"
      :owner="selectedSubmission?.owner||''"
      :assignment-title="filePreview.assignmentTitle||selectedAssignment?.title||selectedCampaign?.assignment_title||reviewTask?.assignment?.title||''"
      :criteria-files="filePreview.mode==='PEER' ? filePreview.criteriaFiles : filePreview.mode==='TEACHER' ? gradingCriteriaFiles : []"
      :criteria-text="filePreview.mode==='PEER' ? filePreview.criteriaText : ''"
      :criteria-locked="filePreview.mode==='PEER'&&Boolean(reviewTask?.review_criteria_locked)"
      :editable="!filePreview.readonly&&(filePreview.mode==='TEACHER'&&role==='TEACHER'||filePreview.mode==='PEER'&&role==='STUDENT'&&!filePreview.initialFeedback)&&Boolean(selectedSubmission)"
      :mode="filePreview.mode"
      :targets="filePreview.targets"
      :target-index="filePreview.targetIndex"
      :initial-feedback="filePreview.initialFeedback"
      :peer-feedback-enabled="filePreview.mode==='TEACHER'&&Boolean(selectedSubmission?.peer_feedbacks?.length)"
      :peer-grade="filePreview.mode==='TEACHER' ? selectedSubmission?.peer_grade||'' : ''"
      :peer-feedbacks="filePreview.mode==='TEACHER' ? selectedSubmission?.peer_feedbacks||[] : []"
      allow-download
      :expanded="filePreview.mode==='PEER'?peerReviewExpanded:fileReviewExpanded"
      :grade-cap="selectedSubmission?.grade_cap||''"
      @close="closeFilePreview"
      @update:expanded="updateFileReviewExpanded"
      @feedback-published="handleFeedbackPublished"
      @clear-feedback="clearTeacherGrade"
      @target-change="changeReviewTarget"
      @external-target="handleExternalReviewTarget"
    />
</template>
