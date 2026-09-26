<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { CheckCircleOutlined, ClockCircleOutlined, DeleteOutlined, DownloadOutlined, ExpandOutlined, PlayCircleOutlined, StopOutlined } from '@ant-design/icons-vue'
import { api } from '../../../api'
import { useShellContext } from '../../../shellContext'

const { classId, session, attendanceSessions, selectedAttendance, activeAttendance, loadAttendanceView, selectAttendance } = useShellContext()
const form = reactive({ title: '', duration_minutes: 15, start_mode: 'NOW', started_at: '' })
const creating = ref(false)
const nowMs = ref(Date.now())
const projecting = ref(false)
const correctionOpen = ref(false)
const correction = reactive({ student_id: '', name: '', status: 'PRESENT', note: '' })
const codeSeconds = computed(() => selectedAttendance.value?.code_expires_at ? Math.max(0, Math.ceil((Date.parse(selectedAttendance.value.code_expires_at) - nowMs.value) / 1000)) : 0)
const sessionSeconds = computed(() => selectedAttendance.value?.expires_at ? Math.max(0, Math.ceil((Date.parse(selectedAttendance.value.expires_at) - nowMs.value) / 1000)) : 0)
const checkedInStudents = computed(() => (selectedAttendance.value?.records || []).filter(record => ['PRESENT', 'LATE'].includes(record.status)))
const avatarText = name => (name || '?').trim().slice(0, 1)
const statusLabels = { PENDING: '未签到', PRESENT: '出勤', LATE: '迟到', ABSENT: '缺勤', LEAVE: '请假' }
const correctionOptions = Object.entries(statusLabels).filter(([value]) => value !== 'PENDING').map(([value, label]) => ({ value, label }))
const dateTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
let tick
let refresh

async function reload() {
  try { await loadAttendanceView() } catch (error) { message.error(error.message) }
}

async function create() {
  if (creating.value) return
  if (form.start_mode === 'SCHEDULED' && (!form.started_at || new Date(form.started_at) <= new Date())) return message.warning('请选择晚于当前时间的开始时间')
  creating.value = true
  try {
    const payload = { title: form.title, duration_minutes: form.duration_minutes, started_at: form.start_mode === 'SCHEDULED' ? new Date(form.started_at).toISOString() : null }
    const created = await api(`/classes/${classId.value}/attendance-sessions`, { method: 'POST', body: JSON.stringify(payload) })
    await reload()
    await selectAttendance(created.id)
    message.success(created.status === 'SCHEDULED' ? '考勤已预约' : '考勤已开始')
  } catch (error) { message.error(error.message) }
  finally { creating.value = false }
}

function end() {
  if (!selectedAttendance.value) return
  Modal.confirm({ title: '结束本次考勤？', content: '结束后考勤码立即失效，仍可手动更正记录。', onOk: async () => {
    try {
      await api(`/attendance-sessions/${selectedAttendance.value.id}/end`, { method: 'POST' })
      projecting.value = false
      await reload()
    } catch (error) { message.error(error.message) }
  } })
}

function remove(item) {
  Modal.confirm({ title: `删除考勤记录“${item.title}”？`, content: '本次学生考勤记录将永久删除，学期考勤分和导出结果也会重新计算。', okText: '删除', okType: 'danger', onOk: async () => {
    try {
      await api(`/attendance-sessions/${item.id}`, { method: 'DELETE' })
      if (selectedAttendance.value?.id === item.id) selectedAttendance.value = null
      if (item.status === 'ACTIVE') projecting.value = false
      await reload()
      message.success('考勤记录已删除')
    } catch (error) { message.error(error.message); throw error }
  } })
}

function edit(record) {
  Object.assign(correction, { student_id: record.student_id, name: record.student_name, status: record.status === 'PENDING' ? 'PRESENT' : record.status, note: record.note || '' })
  correctionOpen.value = true
}

async function saveCorrection() {
  try {
    await api(`/attendance-sessions/${selectedAttendance.value.id}/records/${correction.student_id}`, { method: 'PUT', body: JSON.stringify({ status: correction.status, note: correction.note }) })
    correctionOpen.value = false
    await reload()
    message.success('记录已更新')
  } catch (error) { message.error(error.message) }
}

function exportClass() { window.location.href = `/api/v1/classes/${classId.value}/attendance.xlsx` }
function escape(event) { if (event.key === 'Escape') projecting.value = false }

onMounted(() => {
  form.title = `${new Date().toLocaleDateString('zh-CN')} 考勤`
  tick = setInterval(async () => {
    nowMs.value = Date.now()
    if (selectedAttendance.value?.status === 'ACTIVE' && codeSeconds.value === 0) {
      try { selectedAttendance.value = { ...selectedAttendance.value, ...await api(`/attendance-sessions/${selectedAttendance.value.id}/code`) } } catch (_) {}
    }
  }, 1000)
  refresh = setInterval(async () => {
    if (!activeAttendance.value) return
    try {
      const latest = await api(`/attendance-sessions/${activeAttendance.value.id}`)
      const index = attendanceSessions.value.findIndex(item => item.id === latest.id)
      const previousStatus = index >= 0 ? attendanceSessions.value[index].status : null
      if (index >= 0) attendanceSessions.value[index] = latest
      if (selectedAttendance.value?.id === latest.id) selectedAttendance.value = latest
      if (latest.status !== previousStatus) await reload()
    } catch (_) {}
  }, 5000)
  window.addEventListener('keydown', escape)
})
onBeforeUnmount(() => { clearInterval(tick); clearInterval(refresh); window.removeEventListener('keydown', escape) })
watch(classId, () => { selectedAttendance.value = null; projecting.value = false; reload() })
</script>

<template>
  <div class="page-title attendance-heading"><div><h1>考勤管理</h1><p>{{session.context?.current_class?.semester}} · {{session.context?.current_class?.name}}</p></div><a-button @click="exportClass"><DownloadOutlined/> 导出本学期 XLSX</a-button></div>

  <section class="attendance-start">
    <div class="attendance-section-title"><h2>发起考勤</h2><span v-if="activeAttendance">本班已有进行中或待开始的考勤</span></div>
    <div class="attendance-start-fields">
      <a-input v-model:value="form.title" aria-label="考勤标题" maxlength="100" placeholder="考勤标题" :disabled="!!activeAttendance"/>
      <label>开始时间 <a-radio-group v-model:value="form.start_mode" :disabled="!!activeAttendance" button-style="solid"><a-radio-button value="NOW">立即</a-radio-button><a-radio-button value="SCHEDULED">预约</a-radio-button></a-radio-group></label>
      <a-input v-if="form.start_mode==='SCHEDULED'" v-model:value="form.started_at" type="datetime-local" aria-label="预约开始时间" :disabled="!!activeAttendance"/>
      <label>持续时间 <a-input-number v-model:value="form.duration_minutes" :min="1" :max="120" :disabled="!!activeAttendance"/> 分钟</label>
      <a-button type="primary" :loading="creating" :disabled="!!activeAttendance || !form.title.trim() || (form.start_mode==='SCHEDULED' && !form.started_at)" @click="create"><PlayCircleOutlined/> {{form.start_mode==='SCHEDULED'?'预约':'开始'}}</a-button>
    </div>
  </section>

  <section v-if="selectedAttendance?.status==='ACTIVE'" class="attendance-live">
    <div class="attendance-live-main"><div><span class="attendance-live-label">当前考勤 · {{selectedAttendance.title}}</span><div class="attendance-code">{{selectedAttendance.code || '------'}}</div><span class="attendance-countdown"><ClockCircleOutlined/> {{codeSeconds}} 秒后更新 · {{Math.ceil(sessionSeconds / 60)}} 分钟后结束</span></div><div class="attendance-live-stats"><strong>{{selectedAttendance.present + selectedAttendance.late}} / {{selectedAttendance.total}}</strong><span>已签到</span></div></div>
    <div class="attendance-live-actions"><a-button @click="projecting=true"><ExpandOutlined/> 投屏展示</a-button><a-button danger @click="end"><StopOutlined/> 结束考勤</a-button></div>
  </section>

  <section v-if="selectedAttendance?.status==='SCHEDULED'" class="attendance-live attendance-scheduled"><div><span class="attendance-live-label">待开始 · {{selectedAttendance.title}}</span><div class="attendance-scheduled-time">{{dateTime(selectedAttendance.started_at)}}</div><span class="attendance-countdown">开始后持续 {{Math.round((Date.parse(selectedAttendance.expires_at) - Date.parse(selectedAttendance.started_at)) / 60000)}} 分钟</span></div><a-button danger @click="remove(selectedAttendance)"><DeleteOutlined/> 取消预约</a-button></section>

  <section class="attendance-history"><div class="attendance-section-title"><h2>考勤记录</h2><span>{{attendanceSessions.length}} 次</span></div>
    <a-empty v-if="!attendanceSessions.length" description="暂无考勤记录"/>
    <div v-else class="attendance-session-list">
      <div v-for="item in attendanceSessions" :key="item.id" class="attendance-session-item" :class="{selected:selectedAttendance?.id===item.id}"><button type="button" class="attendance-session-row" @click="selectAttendance(item.id)"><span><strong>{{item.title}}</strong><small>开始：{{dateTime(item.started_at)}}</small></span><a-tag :color="item.status==='ACTIVE'?'processing':item.status==='SCHEDULED'?'warning':'default'">{{item.status==='ACTIVE'?'进行中':item.status==='SCHEDULED'?'待开始':'已结束'}}</a-tag><span class="attendance-session-stats"><span>已签到 {{item.present + item.late}} / {{item.total}}</span><span>迟到 {{item.late}}</span><span>缺勤 {{item.absent}}</span><span>请假 {{item.leave}}</span><span v-if="item.status==='ACTIVE'">待签到 {{item.pending}}</span></span></button><a-button type="text" danger class="attendance-session-delete" :aria-label="`删除考勤记录 ${item.title}`" :title="`删除考勤记录 ${item.title}`" @click="remove(item)"><DeleteOutlined/></a-button></div>
    </div>
  </section>

  <section v-if="selectedAttendance" class="attendance-roster"><div class="attendance-section-title"><h2>{{selectedAttendance.title}} · 学生记录</h2><span>出勤 {{selectedAttendance.present}} · 迟到 {{selectedAttendance.late}} · 请假 {{selectedAttendance.leave}} · {{selectedAttendance.status==='ACTIVE'?'未签到':'缺勤'}} {{selectedAttendance.status==='ACTIVE'?selectedAttendance.pending:selectedAttendance.absent}}</span></div>
    <a-table class="attendance-desktop-table" :data-source="selectedAttendance.records || []" row-key="student_id" size="small" :pagination="{pageSize:20}" :scroll="{x:680}">
      <a-table-column title="学号" data-index="student_no" :width="150"/><a-table-column title="姓名" data-index="student_name" :width="130"/>
      <a-table-column title="状态" :width="110"><template #default="{record}"><a-tag :color="record.status==='PRESENT'?'green':record.status==='LATE'?'orange':record.status==='LEAVE'?'blue':'default'">{{statusLabels[record.status]}}</a-tag></template></a-table-column>
      <a-table-column title="签到时间" :width="200"><template #default="{record}">{{dateTime(record.checked_in_at)}}</template></a-table-column>
      <a-table-column title="备注" data-index="note"/><a-table-column title="操作" :width="90"><template #default="{record}"><a-button type="link" size="small" @click="edit(record)">更正</a-button></template></a-table-column>
    </a-table>
    <div class="attendance-mobile-records">
      <article v-for="record in selectedAttendance.records || []" :key="record.student_id" class="attendance-mobile-record">
        <div><strong>{{record.student_name}}</strong><small>{{record.student_no}}</small></div>
        <a-tag :color="record.status==='PRESENT'?'green':record.status==='LATE'?'orange':record.status==='LEAVE'?'blue':'default'">{{statusLabels[record.status]}}</a-tag>
        <span>签到：{{dateTime(record.checked_in_at)}}</span>
        <p v-if="record.note">{{record.note}}</p>
        <a-button @click="edit(record)">更正</a-button>
      </article>
      <a-empty v-if="!selectedAttendance.records?.length" description="暂无学生记录"/>
    </div>
  </section>

  <a-modal v-model:open="correctionOpen" :title="`更正考勤 · ${correction.name}`" ok-text="保存" @ok="saveCorrection"><div class="attendance-correction"><label>状态<a-select v-model:value="correction.status" :options="correctionOptions"/></label><label>备注<a-textarea v-model:value="correction.note" :rows="3" :maxlength="500"/></label></div></a-modal>

  <div v-if="projecting && selectedAttendance?.status==='ACTIVE'" class="attendance-projection" role="dialog" aria-modal="true" aria-label="考勤投屏">
    <button type="button" class="attendance-projection-close" aria-label="关闭投屏" @click="projecting=false">×</button>
    <span>{{session.context?.current_class?.name}} · {{selectedAttendance.title}}</span>
    <strong>{{selectedAttendance.code || '------'}}</strong>
    <div class="attendance-projection-time">{{codeSeconds}} 秒后更新</div>
    <div class="attendance-projection-foot"><span><CheckCircleOutlined/> 已签到 {{selectedAttendance.present + selectedAttendance.late}} / {{selectedAttendance.total}}</span><span>剩余 {{Math.ceil(sessionSeconds / 60)}} 分钟</span></div>
    <div class="attendance-projection-attendees">
      <div class="attendance-projection-attendees-title">已签到同学</div>
      <div v-if="checkedInStudents.length" class="attendance-projection-attendees-list">
        <div v-for="record in checkedInStudents" :key="record.student_id" class="attendance-projection-attendee" :class="{late:record.status==='LATE'}" :title="`${record.student_name}${record.status==='LATE'?' · 迟到':''}`">
          <span class="attendance-projection-avatar">{{avatarText(record.student_name)}}</span>
          <span class="attendance-projection-name">{{record.student_name}}</span>
        </div>
      </div>
      <div v-else class="attendance-projection-attendees-empty">等待同学签到</div>
    </div>
  </div>
</template>
