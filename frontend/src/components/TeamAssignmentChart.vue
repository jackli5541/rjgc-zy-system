<script setup>
import { computed } from 'vue'
const props = defineProps({ assignments: { type: Array, default: () => [] } })
const submitted = computed(() => props.assignments.filter(item => item.submission.status === 'SUBMITTED').length)
</script>

<template>
  <section class="team-status-chart" aria-label="近期小组作业提交情况">
    <div class="team-chart-summary"><strong>{{submitted}} / {{assignments.length}} 次已提交</strong><div class="team-chart-legend"><span class="on-time">按时提交</span><span class="late">迟交</span><span class="missing">未提交</span></div></div>
    <div class="team-chart-track"><div v-for="item in [...assignments].reverse()" :key="item.id" class="team-chart-column"><a-tooltip :title="`${item.title} · ${item.submission.status==='SUBMITTED'?(item.submission.is_late?'迟交':'按时提交'):'未提交'}`"><div class="team-chart-bar" :class="item.submission.status==='SUBMITTED'?(item.submission.is_late?'late':'on-time'):'missing'"><span>{{item.submission.status==='SUBMITTED'?(item.submission.is_late?'迟交':'已提交'):'未提交'}}</span></div></a-tooltip><strong :title="item.title">{{item.title}}</strong></div></div>
  </section>
</template>
