<script setup>
import AiGradingDraftPanel from '../components/AiGradingDraftPanel.vue'
defineProps({ assignmentId: { type: String, required: true }, submissionVersionId: { type: String, required: true } })
</script>

<template><AiGradingDraftPanel :assignment-id="assignmentId" :submission-version-id="submissionVersionId" /></template>
