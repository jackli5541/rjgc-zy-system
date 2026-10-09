<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { api } from '../../../api'

const props = defineProps({ record: Object, sessionId: String, field: String, statusValue: String, busy: Boolean })
const emit = defineEmits(['saved', 'saving'])
const note = ref(props.record.note || '')
const saving = ref(false)
const dirty = ref(false)
const feedback = ref('')
const options = [{ value: 'PRESENT', label: '出勤' }, { value: 'LATE', label: '迟到' }, { value: 'LEAVE', label: '请假' }, { value: 'ABSENT', label: '缺勤' }]
let timer
watch(() => props.record.note, value => { if (!dirty.value && !saving.value) note.value = value || '' })

async function save(status) {
  clearTimeout(timer)
  if (saving.value || props.busy || (props.field === 'note' && !dirty.value)) return
  const submitted = note.value
  const sessionId = props.sessionId
  const studentId = props.record.student_id
  saving.value = true
  if (props.field === 'status') emit('saving', `${sessionId}-${studentId}`, true)
  feedback.value = '保存中…'
  try {
    const record = await api(`/attendance-sessions/${sessionId}/records/${studentId}`, {
      method: 'PUT', body: JSON.stringify(props.field === 'note' ? { note: submitted } : { status })
    })
    emit('saved', sessionId, record, props.field)
    if (props.field === 'note') {
      dirty.value = note.value !== submitted
      if (!dirty.value) note.value = record.note || ''
    }
    feedback.value = '已保存'
  } catch (error) {
    feedback.value = '保存失败'
    message.error(error.message)
  } finally {
    saving.value = false
    if (props.field === 'status') emit('saving', `${sessionId}-${studentId}`, false)
  }
  if (dirty.value && note.value !== submitted) timer = setTimeout(() => save(), 600)
}

function changeNote(value) {
  note.value = value
  dirty.value = true
  feedback.value = '待保存'
  clearTimeout(timer)
  timer = setTimeout(() => save(), 600)
}
onBeforeUnmount(() => { clearTimeout(timer); if (dirty.value) save() })
</script>

<template>
  <div v-if="field === 'status'" class="attendance-inline-status" :class="{ 'attendance-status-cell': statusValue }">
    <template v-for="option in options" :key="option.value">
      <a-checkbox v-if="!statusValue || statusValue === option.value" :class="`attendance-status-${option.value.toLowerCase()}`" :checked="record.status === option.value" :disabled="saving || busy" :aria-label="`${record.student_name}${option.label}`" @change="save($event.target.checked ? option.value : 'ABSENT')"><template v-if="!statusValue">{{option.label}}</template></a-checkbox>
    </template>
  </div>
  <div v-else class="attendance-inline-note">
    <a-input :value="note" :maxlength="500" :bordered="false" placeholder="添加备注" :aria-label="`${record.student_name}备注`" @update:value="changeNote" @blur="save()" @pressEnter="save()"/>
    <span role="status" :class="{ 'attendance-save-error': feedback === '保存失败' }">{{feedback}}</span>
    <a-button v-if="feedback === '保存失败'" type="link" size="small" @click="save()">重试</a-button>
  </div>
</template>
