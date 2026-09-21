<script setup>
import { computed, ref, watch } from 'vue'
import { DeleteOutlined, DownloadOutlined, EditOutlined, FileTextOutlined, KeyOutlined, ReloadOutlined, SaveOutlined, UserOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { api, exportArchive } from '../api'

const props = defineProps({ student: Object, classId: String, writable: Boolean })
const emit = defineEmits(['close', 'saved', 'reset-password', 'remove', 'preview'])
const data = ref(null)
const loading = ref(false)
const error = ref('')
const editing = ref(false)
const name = ref('')
const saving = ref(false)
const exporting = ref(false)
const activeAssignments = ref([])
const assignmentFilter = ref('ALL')
let generation = 0
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN') : '-'
const sourceLabel = value => ({ TEACHER: '教师评分', PEER: '学生互评', SYSTEM: '系统判定' }[value] || '-')
const completionRate = computed(() => data.value?.summary.total ? Math.round(data.value.summary.submitted / data.value.summary.total * 100) : 0)
const visibleAssignments = computed(() => (data.value?.assignments || []).map((item,index) => ({...item, sequence:index+1})).filter(item => assignmentFilter.value === 'ALL' || (assignmentFilter.value === 'SUBMITTED' ? item.status === 'SUBMITTED' : item.status !== 'SUBMITTED')))
const points = computed(() => (data.value?.assignments || []).map((item, index) => ({ ...item, x: 42 + index * (chartWidth.value - 74) / Math.max(1, (data.value?.assignments.length || 1) - 1), y: item.final_grade ? 20 + ('ABCDE'.indexOf(item.final_grade)) * 25 : null })))
const lines = computed(() => {
  const segments = []
  let segment = []
  for (const point of points.value) {
    if (point.y === null) { if (segment.length) segments.push(segment.join(' ')); segment = [] }
    else segment.push(`${point.x},${point.y}`)
  }
  if (segment.length) segments.push(segment.join(' '))
  return segments
})
const chartWidth = computed(() => Math.max(600, (data.value?.assignments.length || 0) * 65 + 40))
async function load() {
  const current = ++generation
  if (!props.student) { data.value = null; loading.value = false; return }
  loading.value = true
  error.value = ''
  try {
    const result = await api(`/classes/${props.classId}/members/${props.student.id}/portfolio`)
    if (current === generation) { data.value = result; name.value = result.member.name }
  } catch (e) { if (current === generation) error.value = e.message }
  finally { if (current === generation) loading.value = false }
}
watch(() => [props.student?.id, props.classId], () => { data.value = null; editing.value = false; activeAssignments.value = []; assignmentFilter.value = 'ALL'; load() }, { immediate: true })
async function save() {
  if (!name.value.trim()) return message.warning('请填写姓名')
  saving.value = true
  try {
    await api(`/classes/${props.classId}/members/${props.student.id}`, { method: 'PATCH', body: JSON.stringify({ name: name.value.trim() }) })
    editing.value = false
    emit('saved')
    await load()
    message.success('姓名已更新')
  } catch (e) { message.error(e.message) }
  finally { saving.value = false }
}
async function exportStudent() {
  exporting.value = true
  try { await exportArchive(`/classes/${props.classId}/members/${props.student.id}/portfolio.zip`) }
  catch (e) { message.error(e.message) }
  finally { exporting.value = false }
}
</script>

<template>
  <button v-if="student" type="button" class="portfolio-click-away" aria-label="关闭学生档案" @click="emit('close')"/>
  <a-drawer :open="Boolean(student)" title="学生档案" :mask="false" :width="'min(720px, 100vw)'" :get-container="false" :root-style="{position:'fixed'}" :z-index="950" :push="false" root-class-name="student-portfolio-drawer" @close="emit('close')">
    <template #extra><a-space><a-tooltip title="刷新档案"><a-button type="text" shape="circle" :loading="loading" aria-label="刷新档案" @click="load"><ReloadOutlined/></a-button></a-tooltip><a-button :loading="exporting" @click="exportStudent"><DownloadOutlined/> 导出 ZIP</a-button></a-space></template>
    <a-alert v-if="error" type="error" :message="error" show-icon/><a-skeleton v-else-if="loading && !data" active/>
    <template v-if="data">
      <section class="portfolio-section portfolio-identity">
        <div class="portfolio-heading"><div class="portfolio-person"><span class="portfolio-avatar"><UserOutlined/></span><div><h2>{{data.member.name}}</h2><span class="portfolio-student-no">{{data.member.student_no}}</span></div></div><div class="portfolio-inline-stats"><div><span>作业</span><strong>{{data.summary.total}}</strong></div><div><span>已交</span><strong>{{data.summary.submitted}}</strong></div><div><span>未交</span><strong>{{data.summary.missing}}</strong></div><div><span>迟交</span><strong>{{data.summary.late}}</strong></div><div><span>提交率</span><strong>{{completionRate}}%</strong></div></div><a-space><a-tooltip title="编辑姓名"><a-button type="text" shape="circle" :disabled="!writable" aria-label="编辑姓名" @click="editing=!editing"><EditOutlined/></a-button></a-tooltip><a-tooltip title="重置密码"><a-button type="text" shape="circle" :disabled="!writable" aria-label="重置密码" @click="emit('reset-password',data.member)"><KeyOutlined/></a-button></a-tooltip><a-tooltip title="移出教学班"><a-button danger type="text" shape="circle" :disabled="!writable" aria-label="移出教学班" @click="emit('remove',data.member)"><DeleteOutlined/></a-button></a-tooltip></a-space></div>
        <a-space v-if="editing" class="portfolio-edit"><a-input v-model:value="name" maxlength="80" aria-label="学生姓名" @press-enter="save"/><a-button type="primary" :loading="saving" @click="save"><SaveOutlined/> 保存</a-button><a-button @click="editing=false">取消</a-button></a-space>
        <a-descriptions :column="2" size="small"><a-descriptions-item label="小组">{{data.member.team||'未入组'}}</a-descriptions-item><a-descriptions-item label="加入时间">{{formatTime(data.member.joined_at)}}</a-descriptions-item></a-descriptions>
      </section>
      <section v-if="points.some(item=>item.y!==null)" class="portfolio-section">
        <div class="portfolio-section-heading"><h3>等级趋势</h3><div class="portfolio-legend"><span><i/> 已评分</span><span><i class="system"/> 系统判定</span></div></div>
        <div class="portfolio-chart"><svg :viewBox="`0 0 ${chartWidth} 155`" :style="{minWidth:`${chartWidth}px`}" role="img" aria-label="按作业截止时间排序的最终等级趋势"><g v-for="(grade,index) in 'ABCDE'" :key="grade"><text x="6" :y="25+index*25">{{grade}}</text><line x1="30" :y1="20+index*25" :x2="chartWidth" :y2="20+index*25" stroke="#e6e9ec" stroke-dasharray="3 4"/></g><polyline v-for="(line,index) in lines" :key="index" :points="line" fill="none" stroke="#24866e" stroke-width="2"/><g v-for="(point,index) in points" :key="point.assignment_id"><circle v-if="point.y!==null" :cx="point.x" :cy="point.y" r="4" :fill="point.grade_source==='SYSTEM'?'#cf5149':'#24866e'"><title>{{point.title}}：{{point.final_grade}}（{{sourceLabel(point.grade_source)}}）</title></circle><text :x="point.x" y="148" text-anchor="middle">{{index+1}}</text></g></svg></div>
      </section>
      <section class="portfolio-section portfolio-work"><div class="portfolio-section-heading"><h3>作业记录 <small>{{data.assignments.length}}</small></h3><a-segmented v-model:value="assignmentFilter" size="small" :options="[{label:'全部',value:'ALL'},{label:'已提交',value:'SUBMITTED'},{label:'未提交',value:'MISSING'}]"/></div><a-empty v-if="!visibleAssignments.length" description="暂无作业记录"/>
        <a-collapse v-else v-model:active-key="activeAssignments" ghost class="portfolio-assignment-list" expand-icon-position="end"><a-collapse-panel v-for="item in visibleAssignments" :key="item.assignment_id"><template #header><div class="portfolio-assignment-title"><span class="portfolio-sequence">{{String(item.sequence).padStart(2,'0')}}</span><div class="portfolio-assignment-name"><strong>{{item.title}}</strong><small>截止 {{formatTime(item.due_at)}}<span v-if="item.files.length"> · {{item.files.length}} 个附件</span></small></div><a-tag :color="item.status==='SUBMITTED'?(item.is_late?'orange':'green'):'default'">{{item.status==='SUBMITTED'?(item.is_late?'迟交':'已提交'):'未提交'}}</a-tag><span class="portfolio-result" :class="{system:item.grade_source==='SYSTEM'}">{{item.final_grade||'—'}}<small>{{item.final_grade?sourceLabel(item.grade_source):item.status==='SUBMITTED'?'待评分':'暂无等级'}}</small></span></div></template>
          <a-descriptions :column="2" size="small"><a-descriptions-item label="截止时间">{{formatTime(item.due_at)}}</a-descriptions-item><a-descriptions-item label="提交时间">{{formatTime(item.submitted_at)}}</a-descriptions-item><a-descriptions-item label="提交版本">{{item.version_no||'-'}}</a-descriptions-item><a-descriptions-item label="互评等级">{{item.peer_grade||'-'}}</a-descriptions-item><a-descriptions-item label="教师等级">{{item.teacher_grade?.grade||'-'}}</a-descriptions-item><a-descriptions-item label="评分状态">{{item.grade_source==='SYSTEM'?'逾期未交，系统评为 E':item.final_grade?'已评分':item.status==='SUBMITTED'?'待评分':'待提交'}}</a-descriptions-item></a-descriptions>
          <h4>提交附件 <small>{{item.files.length}}</small></h4><div v-if="item.files.length" class="portfolio-files"><div v-for="file in item.files" :key="file.id"><FileTextOutlined/><button class="file-preview-link" @click="emit('preview',file,item.files,item)">{{file.name}}</button><span class="portfolio-file-size">{{Math.max(1,Math.round(file.size/1024))}} KB</span><a-tooltip title="下载附件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`" aria-label="下载附件"><DownloadOutlined/></a-button></a-tooltip></div></div><p v-else class="portfolio-muted">暂无提交附件</p>
        </a-collapse-panel></a-collapse>
      </section>
    </template>
  </a-drawer>
</template>

<style scoped>
.portfolio-click-away{position:fixed;z-index:949;inset:0 min(720px,100vw) 0 0;padding:0;border:0;background:transparent;cursor:default}
.portfolio-section{padding:18px 24px;margin:0;border-bottom:1px solid #e8edf0;background:#fff}.portfolio-heading{display:flex;align-items:center;gap:18px}.portfolio-heading h2{margin:0 0 3px;font-size:20px;line-height:1.35;color:#25343f}.portfolio-person{display:flex;align-items:center;gap:12px;min-width:190px}.portfolio-avatar{display:grid;place-items:center;width:42px;height:42px;flex:0 0 auto;border-radius:8px;background:#eaf3f0;color:#24866e;font-size:20px}.portfolio-student-no{font-size:12px;color:#72808a;font-variant-numeric:tabular-nums}.portfolio-inline-stats{display:grid;grid-template-columns:repeat(4,minmax(58px,1fr));flex:1}.portfolio-inline-stats>div{padding:0 14px;border-left:1px solid #e8edf0}.portfolio-inline-stats span,.portfolio-inline-stats strong{display:block}.portfolio-inline-stats span{color:#7c8992;font-size:10px;white-space:nowrap}.portfolio-inline-stats strong{margin-top:3px;color:#30424c;font-size:18px;line-height:1.2;font-variant-numeric:tabular-nums}.portfolio-inline-stats>div:nth-child(2) strong{color:#21856c}.portfolio-inline-stats>div:nth-child(3) strong{color:#b17929}.portfolio-inline-stats>div:nth-child(4) strong{color:#af5550}.portfolio-identity :deep(.ant-descriptions){margin-top:12px}.portfolio-identity :deep(.ant-descriptions-item){padding-bottom:0}.portfolio-edit{margin-top:12px}.portfolio-overview{padding-top:12px;padding-bottom:12px}.portfolio-progress{display:flex;align-items:center;gap:14px}.portfolio-progress>span{font-size:11px;white-space:nowrap;color:#72808a}.portfolio-progress :deep(.ant-progress){margin:0;flex:1}.portfolio-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.portfolio-section-heading h3{margin:0;font-size:15px;font-weight:600;color:#263640}.portfolio-section-heading h3 small{margin-left:6px;font-size:12px;color:#8b969e;font-weight:400}.portfolio-legend{display:flex;gap:16px;font-size:11px;color:#72808a}.portfolio-legend span{display:flex;align-items:center;gap:6px}.portfolio-legend i{width:6px;height:6px;background:#24866e;border-radius:50%}.portfolio-legend .system{background:#cf5149}.portfolio-chart{overflow-x:auto}.portfolio-chart svg{display:block;width:100%;height:155px}.portfolio-chart text{font-size:12px;fill:#72808a}.portfolio-work{border-bottom:0;padding-bottom:24px}.portfolio-assignment-title{display:grid;grid-template-columns:28px minmax(0,1fr) 66px 78px;gap:12px;width:100%;align-items:center}.portfolio-sequence{color:#9aa5ad;font-size:12px;font-variant-numeric:tabular-nums}.portfolio-assignment-name strong{display:block;font-size:14px;font-weight:500;color:#2c3f4b;overflow-wrap:anywhere;line-height:1.5}.portfolio-assignment-name small{display:block;font-size:11px;color:#84929b;margin-top:4px;line-height:1.5}.portfolio-result{text-align:center;font-size:20px;font-weight:600;color:#21856c}.portfolio-result.system{color:#bd5650}.portfolio-result small{display:block;font-size:10px;font-weight:400;color:#84929b;line-height:1.4}.portfolio-assignment-list :deep(.ant-collapse-item){border-top:1px solid #e8edf0}.portfolio-assignment-list :deep(.ant-collapse-header){padding:14px 0!important;align-items:center!important}.portfolio-assignment-list :deep(.ant-collapse-expand-icon){padding-inline-end:0!important;color:#97a2aa}.portfolio-assignment-list :deep(.ant-collapse-content-box){padding:16px 18px 18px!important;background:#f7f9fa;border-radius:6px;margin-bottom:14px}.portfolio-assignment-list :deep(.ant-tag){margin:0;text-align:center;font-size:11px;border:0}.portfolio-assignment-list h4{font-size:12px;color:#556974;margin:16px 0 8px}.portfolio-assignment-list h4 small{font-weight:400;color:#97a2aa;margin-left:5px}.portfolio-muted{font-size:12px;margin:8px 0;color:#72808a}.portfolio-files{margin:0}.portfolio-files>div{display:flex;align-items:center;min-height:40px;border-bottom:1px solid #e4e9ed;gap:10px}.portfolio-files>div>.anticon{color:#68808c}.portfolio-files .file-preview-link{flex:1;font-size:12px}.portfolio-file-size{font-size:11px;color:#97a2aa;white-space:nowrap}.portfolio-review{padding:10px 0;border-top:1px solid #e6e9ec;font-size:12px}.portfolio-review>div:first-child{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.portfolio-review small{font-size:11px;color:#72808a}.portfolio-review p{white-space:pre-wrap;overflow-wrap:anywhere}.portfolio-review :deep(.rich-text){margin-top:8px;font-size:13px;overflow-wrap:anywhere}@media(max-width:760px){.portfolio-section{padding:16px}.portfolio-heading{align-items:flex-start;flex-wrap:wrap;gap:12px}.portfolio-person{min-width:0;flex:1}.portfolio-heading>.ant-space{flex-shrink:0}.portfolio-inline-stats{order:3;width:100%;flex-basis:100%}.portfolio-inline-stats>div:first-child{border-left:0;padding-left:0}.portfolio-section-heading{flex-wrap:wrap}.portfolio-assignment-title{grid-template-columns:20px minmax(0,1fr) 56px;gap:8px}.portfolio-result{grid-column:2/4;text-align:left;font-size:16px;display:flex;align-items:center;gap:8px}.portfolio-assignment-name small{font-size:10px}.portfolio-assignment-list :deep(.ant-collapse-content-box){padding:14px!important}.portfolio-legend{gap:10px}}
</style>
<style scoped>
.portfolio-person{min-width:150px}.portfolio-inline-stats{grid-template-columns:repeat(5,minmax(42px,1fr))}.portfolio-inline-stats>div{padding:0 9px}.portfolio-inline-stats>div:nth-child(5) strong{color:#1769aa;font-size:15px}.portfolio-section{padding:15px 20px}.portfolio-assignment-list :deep(.ant-collapse-content-box){padding:13px 16px 15px!important}.portfolio-assignment-list :deep(.ant-descriptions-item){padding-bottom:8px}.portfolio-chart svg{height:142px}
@media(max-width:760px){.portfolio-person{min-width:0}.portfolio-inline-stats{grid-template-columns:repeat(5,minmax(0,1fr))}.portfolio-inline-stats>div{padding:0 7px}}
</style>
