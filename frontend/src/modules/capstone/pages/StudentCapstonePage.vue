<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { message, Modal, Input } from 'ant-design-vue'
import { DeleteOutlined, DownOutlined, EditOutlined, EyeOutlined, FileMarkdownOutlined, FolderOpenOutlined, FolderOutlined, LockOutlined, PlusOutlined, TeamOutlined, UpOutlined } from '@ant-design/icons-vue'
import { api } from '../../../api'
import { renderMarkdown } from '../../../markdownPreview'
import OnlineMarkdownWorkspace from '../../../shared/components/OnlineMarkdownWorkspace.vue'
import RichTextViewer from '../../../shared/components/RichTextViewer.vue'
import { useShellContext } from '../../../shellContext'

const { classId } = useShellContext()

const STAGES = [
  { key: 'PROPOSAL', label: '立项' },
  { key: 'REQUIREMENTS', label: '需求' },
  { key: 'DESIGN', label: '设计' },
  { key: 'IMPLEMENTATION', label: '编码与实现' },
  { key: 'TESTING', label: '测试' },
]

const loading = ref(false)
const error = ref('')
const documents = ref([])
const dueAt = ref(null)
const locked = ref(false)
const unlocked = ref(false)
const activeId = ref('')
const context = ref(null)

const teammates = ref([])
const teamName = ref('')
const topicName = ref('')
const myModuleName = computed(() => teammates.value.find(item => item.is_self)?.module_name || '')
const teammatesLoaded = ref(false)
const teammatesCollapsed = ref(true)
const viewMode = ref('own')
const activeTeammate = ref(null)
const teammateDocuments = ref([])
const teammateActiveDoc = ref(null)
const teammateContentHtml = ref('')
const teammateContentLoading = ref(false)

const basePath = computed(() => classId.value ? `/capstone/classes/${classId.value}/workspace` : '')

const docsByStage = computed(() => {
  const map = new Map(STAGES.map(stage => [stage.key, []]))
  for (const doc of documents.value) {
    if (!map.has(doc.stage)) map.set(doc.stage, [])
    map.get(doc.stage).push(doc)
  }
  for (const list of map.values()) list.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'zh-CN'))
  return map
})

const visibleNodes = computed(() => {
  const nodes = []
  for (const stage of STAGES) {
    nodes.push({ nodeType: 'stage', id: stage.key, name: stage.label, depth: 0 })
    for (const doc of docsByStage.value.get(stage.key) || []) {
      nodes.push({ nodeType: 'document', id: doc.id, name: doc.name, depth: 1, stage: stage.key })
    }
  }
  return nodes
})

const activeStageKey = computed(() => documents.value.find(item => item.id === activeId.value)?.stage || '')

function jumpToStage(stageKey) {
  const list = docsByStage.value.get(stageKey) || []
  if (!list[0]) return
  viewMode.value = 'own'
  selectDocument(list[0])
}

const dueLabel = computed(() => {
  if (!dueAt.value) return '教师尚未设置截止时间'
  const text = new Date(dueAt.value).toLocaleString('zh-CN', { hour12: false })
  return locked.value ? `已于 ${text} 截止` : `截止时间：${text}`
})

async function refreshTree(preferredId) {
  if (!basePath.value) return
  loading.value = true; error.value = ''
  try {
    const workspace = await api(basePath.value, { method: 'POST', body: JSON.stringify({}) })
    documents.value = workspace.documents || []
    dueAt.value = workspace.due_at
    locked.value = workspace.locked
    unlocked.value = workspace.unlocked
    if (preferredId && documents.value.some(item => item.id === preferredId)) activeId.value = preferredId
    else if (!documents.value.some(item => item.id === activeId.value)) activeId.value = documents.value[0]?.id || ''
  } catch (err) { error.value = err.message || '大作业加载失败' }
  finally { loading.value = false }
}

function selectDocument(doc) { activeId.value = doc.id }

function clearContext() { context.value = null }
function openContext(event, node) {
  event.preventDefault(); event.stopPropagation()
  const width = 176
  const height = node.nodeType === 'document' ? (locked.value ? 44 : 116) : (locked.value ? 44 : 80)
  context.value = { node, x: Math.min(event.clientX, window.innerWidth - width - 8), y: Math.min(event.clientY, window.innerHeight - height - 8) }
}

function createDocument(stageKey) {
  clearContext()
  let value = ''
  Modal.confirm({
    title: '新建文档',
    content: h(Input, { placeholder: '请输入文档名称', maxlength: 120, onInput: event => { value = event.target.value } }),
    okText: '创建', cancelText: '取消',
    onOk: async () => {
      const name = value.trim()
      if (!name) { message.warning('请输入文档名称'); return Promise.reject() }
      try {
        const item = await api(`${basePath.value}/documents`, { method: 'POST', body: JSON.stringify({ stage: stageKey, name }) })
        message.success('文档已创建'); await refreshTree(item.id)
      } catch (err) { message.error(err.message || '创建失败'); return Promise.reject() }
    }
  })
}

function renameDocument(doc) {
  clearContext()
  let value = doc.name.replace(/\.md$/i, '')
  Modal.confirm({
    title: '重命名文档',
    content: h(Input, { defaultValue: value, placeholder: '请输入文档名称', maxlength: 120, onInput: event => { value = event.target.value } }),
    okText: '保存', cancelText: '取消',
    onOk: async () => {
      const name = value.trim()
      if (!name) { message.warning('请输入文档名称'); return Promise.reject() }
      try {
        await api(`${basePath.value}/documents/${doc.id}`, { method: 'PATCH', body: JSON.stringify({ name }) })
        message.success('已重命名'); await refreshTree(doc.id)
      } catch (err) { message.error(err.message || '重命名失败'); return Promise.reject() }
    }
  })
}

function deleteDocument(doc) {
  clearContext()
  Modal.confirm({
    title: `删除文档"${doc.name}"？`,
    content: '删除后无法恢复；每个阶段至少保留一篇文档。',
    okText: '确认删除', okType: 'danger', cancelText: '取消',
    onOk: async () => {
      try {
        await api(`${basePath.value}/documents/${doc.id}`, { method: 'DELETE' })
        message.success('已删除'); await refreshTree()
      } catch (err) { message.error(err.message || '删除失败') }
    }
  })
}

async function loadTeammates() {
  if (!classId.value) return
  try {
    const data = await api(`/capstone/classes/${classId.value}/teammates`)
    teammates.value = data.members || []
    teamName.value = data.team_name || ''
    topicName.value = data.topic_name || ''
  } catch (err) { /* 组内同学加载失败不影响主流程，静默处理 */ }
  finally { teammatesLoaded.value = true }
}

async function selectTeammateDocument(doc) {
  teammateActiveDoc.value = doc
  teammateContentLoading.value = true
  try {
    const full = await api(`${basePath.value}/documents/${doc.id}`)
    teammateContentHtml.value = renderMarkdown(full.markdown_content || '')
  } catch (err) { message.error(err.message || '加载文档内容失败') }
  finally { teammateContentLoading.value = false }
}

async function openTeammate(member) {
  if (member.is_self) return
  activeTeammate.value = member
  teammateDocuments.value = []
  teammateActiveDoc.value = null
  teammateContentHtml.value = ''
  viewMode.value = 'teammate'
  try {
    const data = await api(`/capstone/classes/${classId.value}/students/${member.id}/documents`)
    teammateDocuments.value = data.documents || []
    if (teammateDocuments.value[0]) await selectTeammateDocument(teammateDocuments.value[0])
  } catch (err) { message.error(err.message || '加载同学文档失败') }
}

function backToOwnDocuments() {
  viewMode.value = 'own'
  activeTeammate.value = null
}

watch(classId, () => { refreshTree(); loadTeammates(); backToOwnDocuments() })
onMounted(() => { refreshTree(); loadTeammates() })
</script>

<template>
  <section class="teaching-materials-page capstone-page" @click="clearContext">
    <header class="page-title capstone-title">
      <div><div class="eyebrow">个人任务</div><h1>大作业</h1><p class="capstone-topic-line">{{dueLabel}} · 课题：{{topicName || '尚未提交选题'}}<template v-if="teamName"> · {{teamName}}</template> · 我的模块：<strong>{{myModuleName || '未分配'}}</strong></p></div>
      <nav class="capstone-stage-strip" aria-label="阶段导航">
        <button
          v-for="(stage, index) in STAGES"
          :key="stage.key"
          type="button"
          class="capstone-stage-chip"
          :class="{active: activeStageKey===stage.key}"
          @click="jumpToStage(stage.key)"
        >
          <span class="index">{{index + 1}}</span>
          <span class="label">{{stage.label}}</span>
          <span class="count">{{(docsByStage.get(stage.key)||[]).length}} 篇</span>
        </button>
      </nav>
      <a-tag v-if="locked && unlocked" color="orange"><LockOutlined/> 已截止 · 教师已为你解锁</a-tag>
      <a-tag v-else-if="locked" color="red"><LockOutlined/> 已截止</a-tag>
      <a-tag v-else color="blue">进行中</a-tag>
    </header>
    <a-alert v-if="error" type="error" show-icon :message="error" class="teaching-materials-alert" />
    <div class="teaching-materials-layout">
      <aside class="teaching-materials-tree">
        <div class="teaching-materials-tree-heading"><span>文档目录</span><small>右击新建/重命名/删除</small></div>
        <a-spin v-if="loading" class="teaching-materials-loading" />
        <div v-else class="teaching-materials-node-list">
          <button v-for="node in visibleNodes" :key="`${node.nodeType}-${node.id}`" type="button" class="teaching-material-node" :class="{selected:node.nodeType==='document'&&activeId===node.id,folder:node.nodeType==='stage'}" :style="{paddingLeft:`${14 + node.depth * 20}px`}" @click.stop="node.nodeType==='document' && selectDocument(node)" @contextmenu="event => openContext(event, node)">
            <FolderOutlined v-if="node.nodeType==='stage'" class="teaching-material-node-icon" />
            <FileMarkdownOutlined v-else class="teaching-material-node-icon file" />
            <span class="teaching-material-node-name">{{node.name}}</span>
          </button>
        </div>
      </aside>
      <main class="teaching-materials-preview capstone-editor">
        <template v-if="viewMode==='own'">
          <div v-if="!activeId" class="teaching-materials-placeholder"><FolderOpenOutlined/><h2>选择左侧文档开始编写</h2><p>点击文档名称即可在线编辑</p></div>
          <OnlineMarkdownWorkspace v-else :key="basePath" :base-path="basePath" :document-id="activeId" hide-document-list :enable-download="false" :writable="!locked" :can-submit="false" />
        </template>
        <template v-else>
          <div class="capstone-readonly-banner"><EyeOutlined/> 只读查看 · 仅供参考，请勿抄袭 —— 正在查看「{{activeTeammate?.display_name}}」的文档<a-button size="small" @click="backToOwnDocuments">返回我的文档</a-button></div>
          <div class="capstone-readonly-body">
            <nav class="capstone-readonly-doc-list">
              <button v-for="doc in teammateDocuments" :key="doc.id" type="button" :class="{active: teammateActiveDoc?.id===doc.id}" @click="selectTeammateDocument(doc)"><FileMarkdownOutlined/> {{doc.name}}</button>
              <a-empty v-if="!teammateDocuments.length" description="该同学还没有文档" />
            </nav>
            <div class="capstone-readonly-content">
              <a-spin v-if="teammateContentLoading" />
              <RichTextViewer v-else :html="teammateContentHtml" />
            </div>
          </div>
        </template>
      </main>
    </div>
    <section class="capstone-teammates">
      <button type="button" class="capstone-teammates-toggle" @click="teammatesCollapsed = !teammatesCollapsed">
        <TeamOutlined/> 组内同学（只读参考）<span v-if="teammates.length" class="count">{{teammates.length}} 人</span>
        <DownOutlined v-if="teammatesCollapsed" /><UpOutlined v-else />
      </button>
      <div v-show="!teammatesCollapsed" class="capstone-teammates-body">
        <a-empty v-if="teammatesLoaded && !teammates.length" description="你还没有加入小组，暂无同组同学" />
        <button v-for="member in teammates" :key="member.id" type="button" class="capstone-teammate-item" :class="{self: member.is_self, active: activeTeammate?.id===member.id}" :disabled="member.is_self" @click="openTeammate(member)">
          <span class="name">{{member.display_name}}<template v-if="member.is_self">（我）</template></span>
          <span class="module">{{member.module_name || '未分配模块'}}</span>
        </button>
      </div>
    </section>
    <div v-if="context" class="teaching-material-context-menu" :style="{left:`${context.x}px`,top:`${context.y}px`}" @click.stop>
      <template v-if="context.node.nodeType==='stage'">
        <button v-if="!locked" type="button" @click="createDocument(context.node.id)"><PlusOutlined/> 新建文档</button>
        <span v-else class="capstone-context-hint">大作业已截止</span>
      </template>
      <template v-else>
        <template v-if="!locked">
          <button type="button" @click="renameDocument(context.node)"><EditOutlined/> 重命名</button>
          <button type="button" class="danger" @click="deleteDocument(context.node)"><DeleteOutlined/> 删除文档</button>
        </template>
        <span v-else class="capstone-context-hint">大作业已截止</span>
      </template>
    </div>
  </section>
</template>
