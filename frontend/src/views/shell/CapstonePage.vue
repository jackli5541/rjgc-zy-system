<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { FileMarkdownOutlined, LockOutlined, UnlockOutlined } from '@ant-design/icons-vue'
import { api } from '../../api'
import { renderMarkdown } from '../../markdownPreview'
import RichTextViewer from '../../components/RichTextViewer.vue'
import { useShellContext } from '../../shellContext'

const { classId } = useShellContext()

const CAPSTONE_STAGES = [
  { key: 'PROPOSAL', label: '立项' },
  { key: 'REQUIREMENTS', label: '需求' },
  { key: 'DESIGN', label: '设计' },
  { key: 'IMPLEMENTATION', label: '编码与实现' },
  { key: 'TESTING', label: '测试' },
]
const reviewLoading = ref(false)
const reviewStudents = ref([])
const reviewDueAt = ref('')
const selectedReviewStudent = ref(null)
const reviewDocuments = ref([])
const selectedReviewDocId = ref('')
const reviewDocHtml = ref('')
const reviewDocLoading = ref(false)
const gradeInputs = ref({})
const gradeSaving = ref('')
const searchQuery = ref('')
const gradeFilter = ref('ALL')
const topicFilter = ref('ALL')

const topicOptions = computed(() => {
  const names = new Set()
  let hasEmpty = false
  for (const student of reviewStudents.value) {
    if (student.topic_name) names.add(student.topic_name)
    else hasEmpty = true
  }
  const options = [{ label: '全部选题', value: 'ALL' }]
  for (const name of [...names].sort((a, b) => a.localeCompare(b, 'zh-CN'))) options.push({ label: name, value: name })
  if (hasEmpty) options.push({ label: '未提交选题', value: '__NONE__' })
  return options
})

const activeGradeStage = computed(() => {
  const doc = reviewDocuments.value.find(item => item.id === selectedReviewDocId.value)
  return doc ? CAPSTONE_STAGES.find(stage => stage.key === doc.stage) || null : null
})

const filteredReviewStudents = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return reviewStudents.value.filter(student => {
    if (query && !`${student.display_name} ${student.module_name} ${student.topic_name}`.toLowerCase().includes(query)) return false
    if (topicFilter.value === '__NONE__' && student.topic_name) return false
    if (topicFilter.value !== 'ALL' && topicFilter.value !== '__NONE__' && student.topic_name !== topicFilter.value) return false
    if (gradeFilter.value === 'GRADED' && student.graded_count < CAPSTONE_STAGES.length) return false
    if (gradeFilter.value === 'UNGRADED' && student.graded_count > 0) return false
    if (gradeFilter.value === 'PARTIAL' && (student.graded_count === 0 || student.graded_count >= CAPSTONE_STAGES.length)) return false
    return true
  })
})

function toLocalInput(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  const pad = value => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function loadReviewStudents() {
  if (!classId.value) return
  reviewLoading.value = true
  try {
    const data = await api(`/capstone/classes/${classId.value}/students`)
    reviewStudents.value = data.students || []
    reviewDueAt.value = toLocalInput(data.due_at)
  } catch (err) { message.error(err.message || '加载学生名单失败') }
  finally { reviewLoading.value = false }
}

async function selectReviewStudent(student) {
  selectedReviewStudent.value = student
  gradeInputs.value = Object.fromEntries(CAPSTONE_STAGES.map(stage => [stage.key, { score: student.grades[stage.key], comment: '' }]))
  reviewDocuments.value = []
  selectedReviewDocId.value = ''
  reviewDocHtml.value = ''
  try {
    const workspace = await api(`/capstone/classes/${classId.value}/workspace?student_id=${student.id}`, { method: 'POST', body: JSON.stringify({}) })
    reviewDocuments.value = workspace.documents || []
    if (reviewDocuments.value[0]) await selectReviewDocument(reviewDocuments.value[0])
  } catch (err) { message.error(err.message || '加载学生文档失败') }
}

async function selectReviewDocument(doc) {
  selectedReviewDocId.value = doc.id
  reviewDocLoading.value = true
  try {
    const full = await api(`/capstone/classes/${classId.value}/workspace/documents/${doc.id}`)
    reviewDocHtml.value = renderMarkdown(full.markdown_content || '')
  } catch (err) { message.error(err.message || '加载文档内容失败') }
  finally { reviewDocLoading.value = false }
}

async function saveGrade(stage) {
  if (!selectedReviewStudent.value) return
  const input = gradeInputs.value[stage] || {}
  gradeSaving.value = stage
  try {
    await api(`/capstone/classes/${classId.value}/students/${selectedReviewStudent.value.id}/grades/${stage}`, { method: 'PUT', body: JSON.stringify({ score: input.score ?? null, comment: input.comment || '' }) })
    selectedReviewStudent.value.grades[stage] = input.score ?? null
    message.success('已保存评分')
  } catch (err) { message.error(err.message || '保存评分失败') }
  finally { gradeSaving.value = '' }
}

async function saveDueAt() {
  try {
    await api(`/capstone/classes/${classId.value}/config`, { method: 'PUT', body: JSON.stringify({ due_at: reviewDueAt.value ? new Date(reviewDueAt.value).toISOString() : null }) })
    message.success('已更新截止时间')
  } catch (err) { message.error(err.message || '设置失败') }
}

async function toggleUnlock(student) {
  try {
    if (student.unlocked) {
      await api(`/capstone/classes/${classId.value}/students/${student.id}/unlock`, { method: 'DELETE' })
      student.unlocked = false
      message.success('已收回解锁')
    } else {
      await api(`/capstone/classes/${classId.value}/students/${student.id}/unlock`, { method: 'POST' })
      student.unlocked = true
      message.success('已解锁，该学生截止后仍可继续编辑')
    }
  } catch (err) { message.error(err.message || '操作失败') }
}

onMounted(loadReviewStudents)
watch(classId, loadReviewStudents)

</script>

<template>
  <div class="capstone-page">
    <header class="page-title capstone-title">
      <div>
        <div class="eyebrow">贯穿16周的个人应用项目</div>
        <h1>大作业管理</h1>
        <p>审批共同选题和个人模块，跟踪每名学生的应用过程并独立验收。</p>
      </div>
    </header>

      <section class="capstone-review-panel">
        <header>
          <h2>学生批阅</h2>
          <div class="capstone-review-due">
            <span>统一截止时间</span>
            <input type="datetime-local" v-model="reviewDueAt" />
            <a-button type="primary" size="small" @click="saveDueAt">保存</a-button>
          </div>
        </header>
        <div class="capstone-review-body">
          <aside class="capstone-review-students">
            <div class="capstone-review-filters">
              <a-input v-model:value="searchQuery" allow-clear placeholder="搜索姓名/模块/选题" size="small" />
              <a-select v-model:value="gradeFilter" size="small" :options="[{label:'全部评分状态',value:'ALL'},{label:'未评分',value:'UNGRADED'},{label:'部分评分',value:'PARTIAL'},{label:'已评满5项',value:'GRADED'}]" />
              <a-select v-model:value="topicFilter" size="small" :options="topicOptions" />
            </div>
            <a-spin v-if="reviewLoading" />
            <a-empty v-else-if="!reviewStudents.length" description="本班暂无学生" />
            <a-empty v-else-if="!filteredReviewStudents.length" description="没有符合筛选条件的学生" />
            <button
              v-for="student in filteredReviewStudents"
              :key="student.id"
              type="button"
              class="capstone-review-student"
              :class="{active:selectedReviewStudent?.id===student.id}"
              @click="selectReviewStudent(student)"
            >
              <span class="avatar">{{student.display_name.slice(0,1)}}</span>
              <span class="info">
                <span class="name">{{student.display_name}}</span>
                <span class="module" v-if="student.module_name">{{student.module_name}}</span>
              </span>
              <span class="status" :class="{unlocked:student.unlocked}">
                <LockOutlined v-if="!student.unlocked"/><UnlockOutlined v-else/>
                <small>{{student.graded_count}}/5</small>
              </span>
            </button>
          </aside>
          <section v-if="selectedReviewStudent" class="capstone-review-detail">
            <div class="capstone-review-toolbar">
              <div class="capstone-review-who">
                <strong>{{selectedReviewStudent.display_name}}</strong>
                <span class="module-tag">{{selectedReviewStudent.module_name || '未分配模块（由组长在选题时填写）'}}</span>
                <span class="topic-tag" v-if="selectedReviewStudent.topic_name">选题：{{selectedReviewStudent.topic_name}}<template v-if="selectedReviewStudent.team_name"> · {{selectedReviewStudent.team_name}}</template></span>
              </div>
              <a-button size="small" @click="toggleUnlock(selectedReviewStudent)">
                {{selectedReviewStudent.unlocked ? '收回解锁' : '单独解锁'}}
              </a-button>
            </div>
            <div class="capstone-review-columns">
              <nav class="capstone-review-docs">
                <button
                  v-for="doc in reviewDocuments"
                  :key="doc.id"
                  type="button"
                  class="capstone-review-doc"
                  :class="{active:selectedReviewDocId===doc.id}"
                  @click="selectReviewDocument(doc)"
                ><FileMarkdownOutlined/> {{doc.name}}</button>
              </nav>
              <div class="capstone-review-main">
                <div v-if="activeGradeStage" class="capstone-review-score-bar">
                  <div class="score-bar-row">
                    <span class="stage-tag"><span class="index">{{CAPSTONE_STAGES.indexOf(activeGradeStage)+1}}</span>{{activeGradeStage.label}}评分</span>
                    <a-input-number v-model:value="gradeInputs[activeGradeStage.key].score" :min="0" :max="100" placeholder="分数" size="small" />
                    <a-button type="primary" size="small" :loading="gradeSaving===activeGradeStage.key" @click="saveGrade(activeGradeStage.key)">保存</a-button>
                    <span class="progress-tag">{{selectedReviewStudent.graded_count}}/5 已评分</span>
                  </div>
                  <a-textarea v-model:value="gradeInputs[activeGradeStage.key].comment" placeholder="评语（可选）" :auto-size="{minRows:2,maxRows:6}" size="small" />
                </div>
                <div class="capstone-review-content">
                  <a-spin v-if="reviewDocLoading" />
                  <RichTextViewer v-else :html="reviewDocHtml" />
                </div>
              </div>
            </div>
          </section>
          <a-empty v-else description="选择左侧学生查看文档与评分" class="capstone-review-placeholder" />
        </div>
      </section>
  </div>
</template>

<style scoped>
.capstone-review-panel{margin-bottom:20px;border:1px solid #dce6e9;border-radius:10px;background:#f8fbfa;box-shadow:0 2px 12px rgba(22,55,63,.05)}.capstone-review-panel>header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 20px;border-bottom:1px solid #dbe7e4;border-radius:10px 10px 0 0}.capstone-review-panel>header h2{margin:0;color:#20373f;font-size:16px;font-weight:700}.capstone-review-due{display:flex;align-items:center;gap:8px;padding:5px 6px 5px 14px;border:1px solid #d7e5e2;border-radius:20px;background:#eef4f3;color:#55717b;font-size:12px}.capstone-review-due input{padding:4px 8px;border:1px solid #d3dfdc;border-radius:14px;background:#fff;font:inherit}.capstone-review-body{display:grid;grid-template-columns:230px minmax(0,1fr)}.capstone-review-students{padding:10px;min-height:0;border-right:1px solid #dbe7e4;overflow-y:auto;max-height:78vh}.capstone-review-filters{display:flex;flex-direction:column;gap:6px;margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #e2e8ea}.capstone-review-filters .ant-select{width:100%}.capstone-review-student{display:grid;grid-template-columns:30px minmax(0,1fr) auto;align-items:center;gap:9px;width:100%;margin-bottom:2px;padding:8px 10px;border:0;border-radius:7px;background:transparent;color:inherit;text-align:left;cursor:pointer;transition:background .15s}.capstone-review-student:hover{background:#eef5f3}.capstone-review-student.active{background:#e5f1ed;color:#176b78;box-shadow:inset 3px 0 #176b78}.capstone-review-student .avatar{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#e3ecec;color:#4c6f74;font-size:12px;font-weight:700}.capstone-review-student.active .avatar{background:#176b78;color:#fff}.capstone-review-student .info{display:flex;flex-direction:column;gap:2px;min-width:0}.capstone-review-student .name{overflow:hidden;font-size:13px;font-weight:600;text-overflow:ellipsis;white-space:nowrap}.capstone-review-student .module{overflow:hidden;color:#4e8074;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.capstone-review-student .status{display:flex;flex-direction:column;align-items:center;gap:2px;color:#b6524b;font-size:9px}.capstone-review-student .status.unlocked{color:#4e8044}.capstone-review-detail{padding:16px 18px}.capstone-review-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}.capstone-review-who{display:flex;align-items:baseline;gap:10px;min-width:0}.capstone-review-who strong{font-size:15px;white-space:nowrap}.capstone-review-who .module-tag{overflow:hidden;color:#55717b;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.capstone-review-who .topic-tag{overflow:hidden;color:#4e8074;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.capstone-review-columns{display:grid;grid-template-columns:170px minmax(0,1fr);gap:16px;align-items:start}.capstone-review-docs{display:flex;flex-direction:column;gap:4px;min-height:0;max-height:74vh;overflow-y:auto}.capstone-review-doc{display:flex;align-items:center;gap:6px;padding:7px 9px;border:0;border-radius:6px;background:#fff;color:#3c5262;font-size:12px;text-align:left;cursor:pointer;transition:background .15s}.capstone-review-doc:hover{background:#f1f7f6}.capstone-review-doc.active{background:#e5f1ed;color:#176b78;font-weight:600}.capstone-review-main{min-height:0;max-height:74vh;overflow-y:auto}.capstone-review-content{min-height:400px;padding:20px 24px;border:1px solid #e2e8ea;border-radius:8px;background:#fff;box-shadow:0 1px 4px rgba(22,55,63,.03)}.capstone-review-score-bar{position:sticky;top:0;z-index:2;display:flex;flex-direction:column;gap:8px;margin-bottom:12px;padding:9px 12px;border:1px solid #d7e5e2;border-radius:8px;background:#eef4f3;box-shadow:0 2px 8px rgba(22,55,63,.06)}.capstone-review-score-bar .score-bar-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px}.capstone-review-score-bar .stage-tag{display:flex;align-items:center;gap:7px;flex:0 0 auto;color:#176b78;font-size:12px;font-weight:700;white-space:nowrap}.capstone-review-score-bar .stage-tag .index{display:grid;place-items:center;width:19px;height:19px;border-radius:50%;background:#176b78;color:#fff;font-size:10px;font-weight:700}.capstone-review-score-bar .ant-input-number{width:90px;flex:0 0 auto}.capstone-review-score-bar .progress-tag{flex:1;text-align:right;color:#8b989d;font-size:11px;white-space:nowrap}.capstone-review-score-bar .ant-input{width:100%;font-size:12px}.capstone-review-placeholder{margin:60px auto}
@media(max-width:900px){.capstone-review-columns{grid-template-columns:1fr}.capstone-review-docs{flex-direction:row;overflow-x:auto;max-height:none}}
.capstone-page{padding:4px 0 40px;color:#293d48}.capstone-title{align-items:flex-end}.stage-label{min-width:0;font-size:13px;font-weight:600;text-align:left}
@media(max-width:760px){.capstone-title{align-items:stretch}}
</style>
