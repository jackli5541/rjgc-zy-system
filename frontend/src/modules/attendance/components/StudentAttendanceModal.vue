<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { CheckCircleOutlined } from '@ant-design/icons-vue'
import { api } from '../../../api'
import { useShellContext } from '../../../shellContext'

const { attendanceOpen, classId } = useShellContext()
const data = ref({ active: null, recent: [] })
const code = ref('')
const submitting = ref(false)
const loading = ref(false)
const statusLabels = { PENDING: '待签到', PRESENT: '出勤', LATE: '迟到', ABSENT: '缺勤', LEAVE: '请假' }
const activeRecord = computed(() => data.value.active?.record)
const displayStatus = item => item.status === 'ACTIVE' && item.record.status === 'ABSENT' && !item.record.source ? 'PENDING' : item.record.status
let refresh

async function load() {
  if (!classId.value) return
  loading.value = true
  try { data.value = await api(`/classes/${classId.value}/attendance/current`) }
  catch (error) { message.error(error.message) }
  finally { loading.value = false }
}

async function checkIn() {
  if (!data.value.active || submitting.value) return
  submitting.value = true
  try {
    await api(`/attendance-sessions/${data.value.active.id}/check-in`, { method: 'POST', body: JSON.stringify({ code: code.value }) })
    code.value = ''
    await load()
    message.success('签到成功')
  } catch (error) { message.error(error.message) }
  finally { submitting.value = false }
}

watch(attendanceOpen, open => {
  clearInterval(refresh)
  if (open) { load(); refresh = setInterval(load, 10000) }
  else code.value = ''
})
watch(classId, () => { if (attendanceOpen.value) load() })
onBeforeUnmount(() => clearInterval(refresh))
</script>

<template>
  <a-modal v-model:open="attendanceOpen" title="考勤" :footer="null" :width="430">
    <a-spin :spinning="loading">
      <div v-if="data.active" class="student-attendance-active"><strong>{{data.active.title}}</strong><span>{{new Date(data.active.expires_at).toLocaleString('zh-CN', {hour12:false})}} 截止</span>
        <div v-if="activeRecord?.status==='PRESENT'||activeRecord?.status==='LATE'||activeRecord?.status==='LEAVE'" class="student-attendance-success"><CheckCircleOutlined/> {{statusLabels[activeRecord.status]}}</div>
        <div v-else class="student-attendance-entry"><a-input v-model:value="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="输入 6 位考勤码" aria-label="考勤码" @pressEnter="checkIn"/><a-button type="primary" :disabled="!/^[0-9]{6}$/.test(code)" :loading="submitting" @click="checkIn">签到</a-button></div>
      </div>
      <a-empty v-else description="当前没有进行中的考勤"/>
      <div v-if="data.recent.length" class="student-attendance-recent"><h3>最近记录</h3><div v-for="item in data.recent.slice(0,5)" :key="item.id"><span>{{item.title}}<small v-if="item.status==='SCHEDULED'">{{new Date(item.started_at).toLocaleString('zh-CN', {hour12:false})}} 开始</small></span><a-tag :color="item.status==='SCHEDULED'?'orange':displayStatus(item)==='PRESENT'?'green':displayStatus(item)==='LATE'?'orange':displayStatus(item)==='LEAVE'?'blue':'default'">{{item.status==='SCHEDULED'?'待开始':statusLabels[displayStatus(item)]}}</a-tag></div></div>
    </a-spin>
  </a-modal>
</template>
