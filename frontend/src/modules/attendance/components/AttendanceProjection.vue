<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CloseOutlined, ClockCircleOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'
import { recentCheckedInRecords } from '../records'
import { useProjectionFeedback } from '../composables/useProjectionFeedback'

const props = defineProps({
  attendance: { type: Object, required: true },
  className: { type: String, default: '' },
  codeSeconds: { type: Number, default: 0 },
  sessionSeconds: { type: Number, default: 0 },
})
const emit = defineEmits(['close'])
const attendance = computed(() => props.attendance)
const { newcomers, highlightedIds, feedbackText, feedbackKey, completed } = useProjectionFeedback(attendance, ref(true))
const checkedInStudents = computed(() => recentCheckedInRecords(props.attendance.records))
const checkedCount = computed(() => props.attendance.present + props.attendance.late)
const progress = computed(() => props.attendance.total ? Math.min(100, Math.round(checkedCount.value / props.attendance.total * 100)) : 0)
const digits = computed(() => String(props.attendance.code || '------').split(''))
const remainingTime = computed(() => `${String(Math.floor(props.sessionSeconds / 60)).padStart(2, '0')}:${String(props.sessionSeconds % 60).padStart(2, '0')}`)
const feedbackIsLate = computed(() => !completed.value && newcomers.value.length === 1 && newcomers.value[0].status === 'LATE')
const attendeesList = ref(null)
const celebrationParticles = Array.from({ length: 64 }, (_, index) => ({
  left: `${(index * 37) % 100}%`,
  '--confetti-delay': `${(index % 8) * .08}s`,
  '--confetti-duration': `${2 + (index % 5) * .18}s`,
  '--confetti-drift': `${((index * 29) % 180) - 90}px`,
  '--confetti-color': ['#165dff', '#8b5cf6', '#ffba49', '#22c99a', '#ff729f'][index % 5],
}))
const closeButton = ref(null)
let previousFocus
const avatarText = name => (name || '?').trim().slice(0, 1)
const avatarTone = studentId => {
  const text = String(studentId)
  return [...text].reduce((total, character) => total + character.charCodeAt(0), 0) % 4
}

watch(feedbackKey, () => { if (attendeesList.value) attendeesList.value.scrollTop = 0 }, { flush: 'post' })
onMounted(() => { previousFocus = document.activeElement; closeButton.value?.focus({ preventScroll: true }) })
onBeforeUnmount(() => { if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true }) })
</script>

<template>
  <div class="attendance-projection" role="dialog" aria-modal="true" aria-label="考勤投屏">
    <header class="projection-header">
      <div class="projection-brand"><span class="projection-brand-mark" aria-hidden="true"><i/><i/><i/><i/></span><h1>{{className}}</h1></div>
      <div class="projection-header-actions"><span class="projection-live"><i/> 签到进行中</span><button ref="closeButton" type="button" class="projection-close" aria-label="关闭投屏" @click="emit('close')"><CloseOutlined/></button></div>
    </header>

    <div v-if="completed" :key="`celebration-${feedbackKey}`" class="projection-celebration" aria-hidden="true">
      <i v-for="(particle,index) in celebrationParticles" :key="index" class="projection-confetti" :class="{'is-round':index%3===0}" :style="particle"/>
      <span class="projection-celebration-halo"/>
    </div>
    <div class="projection-layout" :class="{'projection-all-present':completed}">
      <section class="projection-stage" aria-label="考勤码与签到进度">
        <div class="projection-stage-heading"><h2>{{attendance.title}}</h2><p>输入签到码</p></div>
        <div class="projection-code" :aria-label="`签到码 ${attendance.code || '暂未生成'}`"><span v-for="(digit,index) in digits" :key="index" aria-hidden="true">{{digit}}</span></div>
        <div class="projection-code-expiry"><ClockCircleOutlined/><strong>{{codeSeconds}}s</strong> 后更新</div>

        <div class="projection-feedback-slot" role="status" aria-live="polite" aria-atomic="true">
          <Transition name="projection-feedback">
            <div v-if="newcomers.length" :key="feedbackKey" class="projection-feedback-card" :class="{late:feedbackIsLate,completed}">
              <span class="projection-success-icon" aria-hidden="true"><svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="16"/><path d="m12 20 5 5 11-11"/></svg></span>
              <div><strong>{{completed?'全员到齐！':newcomers.length===1?newcomers[0].student_name:feedbackText}}</strong><span class="projection-feedback-label">{{completed?`${checkedCount} 人，全部签到完成`:feedbackIsLate?'已签到 · 迟到':'签到成功'}}</span></div>
              <span class="projection-feedback-badge">{{completed?'100%':`+${newcomers.length}`}}</span>
            </div>
          </Transition>
        </div>

        <div class="projection-stage-footer">
          <div class="projection-metrics"><div><span>已签到人数</span><p><Transition name="projection-number" mode="out-in"><strong :key="checkedCount">{{checkedCount}}</strong></Transition><span>/ {{attendance.total}} 人</span></p></div><div class="projection-timer"><span>距离结束</span><strong>{{remainingTime}}</strong></div></div>
          <div class="projection-progress" role="progressbar" aria-label="签到进度" :aria-valuenow="checkedCount" :aria-valuemin="0" :aria-valuemax="attendance.total"><div :style="{width:`${progress}%`}"/></div>
        </div>
      </section>

      <aside class="projection-roster" aria-label="最近签到名单">
        <div class="projection-roster-heading"><h2>最近签到</h2><span class="projection-roster-total">{{checkedInStudents.length}} 人</span></div>
        <div ref="attendeesList" class="projection-roster-scroll">
          <TransitionGroup name="projection-person" tag="div" class="projection-people">
            <div v-for="record in checkedInStudents" :key="record.student_id" class="projection-person" :class="{late:record.status==='LATE',fresh:highlightedIds.has(record.student_id)}" :title="`${record.student_name}${record.status==='LATE'?' · 迟到':''}`">
              <span class="projection-person-avatar" :class="`tone-${avatarTone(record.student_id)}`">{{avatarText(record.student_name)}}<span class="projection-person-check"><CheckCircleOutlined/></span></span>
              <strong>{{record.student_name}}</strong><span v-if="record.status==='LATE'" class="projection-person-caption">迟到</span>
            </div>
          </TransitionGroup>
          <div v-if="!checkedInStudents.length" class="projection-empty"><span class="projection-empty-symbol" aria-hidden="true"><CheckCircleOutlined/></span><strong>等待签到</strong></div>
        </div>
      </aside>
    </div>
  </div>
</template>
