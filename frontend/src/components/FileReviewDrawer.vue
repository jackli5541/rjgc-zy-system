<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ArrowDownOutlined, ArrowUpOutlined, CaretRightOutlined, CommentOutlined, DeleteOutlined, DownloadOutlined, ExpandOutlined, HighlightOutlined, LeftOutlined, RightOutlined, StrikethroughOutlined, UnderlineOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { api, randomUUID } from '../api'
import { loadMarkdownPreview } from '../markdownPreview'
import PdfDocumentViewer from './PdfDocumentViewer.vue'
import RichTextEditor from './RichTextEditor.vue'
import RichTextViewer from './RichTextViewer.vue'

const props = defineProps({
  open: Boolean,
  files: { type: Array, default: () => [] },
  initialIndex: { type: Number, default: 0 },
  submissionVersionId: { type: String, default: '' },
  owner: { type: String, default: '' },
  assignmentTitle: { type: String, default: '' },
  editable: Boolean,
  mode: { type: String, default: 'TEACHER' },
  targets: { type: Array, default: () => [] },
  targetIndex: { type: Number, default: 0 },
  initialFeedback: { type: Object, default: null },
  peerFeedbackEnabled: Boolean,
  peerGrade: { type: String, default: '' },
  peerFeedbacks: { type: Array, default: () => [] },
  allowDownload: Boolean,
  expanded: Boolean
})
const emit = defineEmits(['close', 'feedback-published', 'clear-feedback', 'target-change', 'external-target', 'update:expanded'])
const index = ref(0)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const richHtml = ref('')
const binaryUrl = ref('')
const selectedAnnotationId = ref('')
const teacherAnnotationsExpanded = ref(false)
const peerAnnotationsExpanded = ref(false)
const pendingSelection = ref(null)
const selectedColor = ref('YELLOW')
const drawerRoot = ref(null)
const documentStage = ref(null)
const documentViewer = ref(null)
const overallEditor = ref(null)
const commentEditor = ref(null)
const selectionMenu = reactive({ open: false, left: 0, top: 0 })
const commentComposer = reactive({ open: false, visible: true, mode: 'new', annotationId: '', left: 0, top: 0, value: '' })
let loadSequence = 0
let positionFrame = 0
let feedbackBaseline = ''
let drawerAnimationTimer
const drawerAnimating = ref(false)
const toggleExpanded = () => {
  clearTimeout(drawerAnimationTimer)
  drawerAnimating.value = true
  emit('update:expanded', !props.expanded)
  drawerAnimationTimer = setTimeout(() => { drawerAnimating.value = false }, 220)
}
const feedback = reactive({ status: null, revision: 0, grade: undefined, comment: '', annotations: [], published_at: null, has_draft: false })
const externalWarning = ref(false)

const activeFile = computed(() => props.files[index.value] || null)
const renderType = computed(() => activeFile.value?.render_type || (/\.pdf$/i.test(activeFile.value?.name || '') ? 'PDF' : /\.(md|html?)$/i.test(activeFile.value?.name || '') ? 'RICH_TEXT' : /\.(png|jpe?g|gif|webp)$/i.test(activeFile.value?.name || '') ? 'IMAGE' : 'DOWNLOAD_ONLY'))
const activeAnnotations = computed(() => feedback.annotations.filter(item => item.file_id === activeFile.value?.id))
const visiblePeerFeedbacks = computed(() => props.mode === 'TEACHER' ? props.peerFeedbacks : [])
const activePeerAnnotations = computed(() => visiblePeerFeedbacks.value.flatMap(peer => (peer.annotations || [])
  .filter(item => item.file_id === activeFile.value?.id)
  .map(item => ({ ...item, color: 'PURPLE', readonly: true, evaluator_name: peer.evaluator_name, peer_grade: peer.grade }))))
const previewAnnotations = computed(() => [...activeAnnotations.value, ...activePeerAnnotations.value])
const selectedAnnotation = computed(() => previewAnnotations.value.find(item => item.id === selectedAnnotationId.value) || null)
const hasFeedbackPanel = computed(() => Boolean(props.submissionVersionId) && (props.editable || feedback.status))
const hasTargetNavigation = computed(() => props.mode === 'TEACHER' && props.targets.length > 1)
const colors = [
  { value: 'YELLOW', label: '黄色' }, { value: 'GREEN', label: '绿色' },
  { value: 'RED', label: '红色' }, { value: 'BLUE', label: '蓝色' }
]
const markTypes = [
  { value: 'HIGHLIGHT', label: '高亮' }, { value: 'UNDERLINE', label: '下划线' },
  { value: 'STRIKETHROUGH', label: '删除线' }, { value: 'COMMENT', label: '批注' }
]

function resetFeedback(value = {}) {
  stopSpeechInput()
  const grade = props.mode === 'TEACHER' && !value.status ? undefined : value.grade
  Object.assign(feedback, { status: null, revision: 0, grade: undefined, comment: '', annotations: [], published_at: null, has_draft: false }, value, { grade, revision: value.revision ?? value.version ?? 0 })
  feedback.annotations = (value.annotations || []).map(item => ({ ...item, mark_type: item.mark_type || (item.comment ? 'COMMENT' : 'HIGHLIGHT'), color: item.color || 'YELLOW' }))
  selectedAnnotationId.value = ''
  commentComposer.open = false
  dismissTransient()
  feedbackBaseline = JSON.stringify(feedbackPayload())
  externalWarning.value = false
}

function stopSpeechInput() {
  overallEditor.value?.stopSpeechRecognition?.()
  commentEditor.value?.stopSpeechRecognition?.()
}

function feedbackDirty() {
  return props.editable && JSON.stringify(feedbackPayload()) !== feedbackBaseline
}

function handleExternalSubmission(record) {
  if (!props.open) return
  if (feedbackDirty()) { externalWarning.value = true; return }
  if (record?.submission_version_id && record.submission_version_id !== props.submissionVersionId) emit('external-target', record)
  else loadFeedback()
}

defineExpose({ handleExternalSubmission })

function releaseBinaryUrl() {
  if (binaryUrl.value?.startsWith('blob:')) URL.revokeObjectURL(binaryUrl.value)
  binaryUrl.value = ''
}

async function loadFeedback() {
  if (!props.submissionVersionId) return resetFeedback()
  if (props.initialFeedback) return resetFeedback(props.initialFeedback)
  const path = props.mode === 'PEER' ? `/submission-versions/${props.submissionVersionId}/peer-feedback` : `/submission-versions/${props.submissionVersionId}/feedback`
  try { resetFeedback(await api(path)) }
  catch (loadError) { resetFeedback(); message.error(loadError.message) }
}

async function loadFile() {
  const sequence = ++loadSequence
  releaseBinaryUrl(); richHtml.value = ''; error.value = ''
  const file = activeFile.value
  if (!file) return
  if (!file.previewable || file.download_only || renderType.value === 'DOWNLOAD_ONLY') {
    error.value = file.preview_error || '该文件格式暂不支持在线预览。'
    return
  }
  loading.value = true
  try {
    if (renderType.value === 'RICH_TEXT') {
      if (/\.md$/i.test(file.name || '')) {
        const { url } = await api(`/files/${file.id}/preview-url`)
        const html = await loadMarkdownPreview(url)
        if (sequence === loadSequence) richHtml.value = html
      } else {
        throw new Error('仅支持 Markdown 文档在线预览')
      }
    } else if (renderType.value === 'IMAGE') {
      const response = await fetch(`/api/v1/files/${file.id}/preview`, { credentials: 'include' })
      if (!response.ok) throw new Error('图片加载失败')
      const url = URL.createObjectURL(await response.blob())
      if (sequence === loadSequence) binaryUrl.value = url
      else URL.revokeObjectURL(url)
    } else binaryUrl.value = `/api/v1/files/${file.id}/preview`
  } catch (loadError) { if (sequence === loadSequence) error.value = loadError.message || '文件预览加载失败' }
  finally { if (sequence === loadSequence) loading.value = false }
}

function anchoredPosition(rect, width, height) {
  const bounds = documentViewer.value?.viewportRect?.() || documentStage.value?.getBoundingClientRect() || { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight, width: window.innerWidth, height: window.innerHeight }
  const usableWidth = Math.min(width, Math.max(280, bounds.width - 24))
  const minLeft = bounds.left + 12
  const maxLeft = Math.max(minLeft, bounds.right - usableWidth - 12)
  const left = Math.max(minLeft, Math.min(maxLeft, rect.left + rect.width / 2 - usableWidth / 2))
  const above = rect.top - height - 10
  const below = rect.bottom + 10
  const top = above >= bounds.top + 12 ? above : Math.min(bounds.bottom - height - 12, below)
  return { left, top: Math.max(bounds.top + 12, top) }
}

function updateExistingComposerPosition() {
  if (!commentComposer.open || commentComposer.mode !== 'edit' || !commentComposer.annotationId) return
  const rect = documentViewer.value?.annotationRect?.(commentComposer.annotationId)
  const bounds = documentViewer.value?.viewportRect?.() || documentStage.value?.getBoundingClientRect()
  if (!rect || !bounds || rect.bottom < bounds.top || rect.top > bounds.bottom || rect.right < bounds.left || rect.left > bounds.right) {
    commentComposer.visible = false
    return
  }
  Object.assign(commentComposer, { ...anchoredPosition(rect, 330, props.editable ? 230 : 150), visible: true })
}

function scheduleComposerPosition() {
  if (positionFrame) return
  positionFrame = requestAnimationFrame(() => { positionFrame = 0; updateExistingComposerPosition() })
}

function selectionToolbarPosition(rect) {
  const width = Math.min(300, window.innerWidth - 24)
  const height = 46
  const left = Math.max(12, Math.min(window.innerWidth - width - 12, rect.left + rect.width / 2 - width / 2))
  const below = rect.bottom + 12
  const top = below + height <= window.innerHeight - 12 ? below : rect.top - height - 12
  return { left, top: Math.max(12, top) }
}

function clearBrowserSelection() { window.getSelection()?.removeAllRanges() }

function dismissTransient(clearSelection = true) {
  selectionMenu.open = false
  pendingSelection.value = null
  if (commentComposer.mode === 'new') commentComposer.open = false
  if (clearSelection) clearBrowserSelection()
}

function handleSelection(payload) {
  if (!props.editable) return
  selectedAnnotationId.value = ''
  pendingSelection.value = { ...payload, fileId: activeFile.value?.id }
  commentComposer.open = false
  const position = selectionToolbarPosition(payload.viewportRect)
  Object.assign(selectionMenu, { open: true, ...position })
}

function addAnnotation(payload, markType, color, comment = '') {
  if (!props.editable || !payload.fileId) return null
  const annotation = { id: randomUUID(), file_id: payload.fileId, kind: payload.kind, mark_type: markType, color, anchor: payload.anchor, comment }
  feedback.annotations.push(annotation)
  selectedAnnotationId.value = annotation.id
  return annotation
}

function applyMark(markType) {
  if (!pendingSelection.value) return
  addAnnotation(pendingSelection.value, markType, selectedColor.value)
  dismissTransient()
}

function openCommentComposer() {
  if (!pendingSelection.value) return
  const position = anchoredPosition(pendingSelection.value.viewportRect, 330, 230)
  Object.assign(commentComposer, { open: true, mode: 'new', annotationId: '', value: '', ...position })
  selectionMenu.open = false
}

function htmlHasText(value) {
  const element = document.createElement('div')
  element.innerHTML = value || ''
  return Boolean(element.textContent?.trim())
}

function submitComment() {
  if (!htmlHasText(commentComposer.value)) return message.warning('请填写批注内容')
  if (commentComposer.mode === 'new' && pendingSelection.value) {
    addAnnotation(pendingSelection.value, 'COMMENT', selectedColor.value, commentComposer.value)
  } else {
    const annotation = feedback.annotations.find(item => item.id === commentComposer.annotationId)
    if (annotation) { annotation.mark_type = 'COMMENT'; annotation.comment = commentComposer.value }
  }
  stopSpeechInput()
  commentComposer.open = false
  pendingSelection.value = null
  clearBrowserSelection()
}

function cancelComment() {
  stopSpeechInput()
  commentComposer.open = false
  pendingSelection.value = null
  clearBrowserSelection()
}

function showAnnotationComment(annotation, rect) {
  const position = anchoredPosition(rect, 330, props.editable ? 230 : 150)
  Object.assign(commentComposer, { open: true, visible: true, mode: 'edit', annotationId: annotation.id, value: annotation.comment || '', ...position })
}

function selectAnnotation(payload, openBubble = true) {
  const id = typeof payload === 'string' ? payload : payload.id
  selectedAnnotationId.value = id
  const fromSidebar = typeof payload === 'string'
  if (fromSidebar) documentViewer.value?.focusAnnotation?.(id)
  requestAnimationFrame(() => drawerRoot.value?.querySelector(`[data-sidebar-annotation-id="${id}"]`)?.scrollIntoView({ block: 'nearest' }))
  const annotation = previewAnnotations.value.find(item => item.id === id)
  const shouldOpen = openBubble && (typeof payload === 'string' || payload.openBubble !== false)
  if (!shouldOpen || !annotation || annotation.mark_type !== 'COMMENT') return
  if (!fromSidebar && payload.viewportRect) return showAnnotationComment(annotation, payload.viewportRect)
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const rect = documentViewer.value?.annotationRect?.(id)
    if (rect) showAnnotationComment(annotation, rect)
  }))
}

function addCommentToMark(annotation, event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const position = anchoredPosition(rect, 330, 230)
  Object.assign(commentComposer, { open: true, mode: 'edit', annotationId: annotation.id, value: annotation.comment || '', ...position })
}

function markTypeOptions(annotation) {
  if (annotation.comment && htmlHasText(annotation.comment)) return markTypes.filter(item => item.value === 'COMMENT')
  return annotation.kind === 'PDF_TEXT_OR_REGION' && !annotation.anchor?.quote ? markTypes.filter(item => item.value === 'HIGHLIGHT') : markTypes.filter(item => item.value !== 'COMMENT')
}

function fileOptionLabel(file) {
  const count = feedback.annotations.filter(item => item.file_id === file.id).length
  return count ? `${file.name} (${count})` : file.name
}

function handleGlobalPointer(event) {
  if (event.target.closest?.('.selection-action-menu,.annotation-composer')) return
  if (selectionMenu.open) dismissTransient()
}

function handleGlobalScroll() {
  if (selectionMenu.open || (commentComposer.open && commentComposer.mode === 'new')) dismissTransient()
  if (commentComposer.open && commentComposer.mode === 'edit') scheduleComposerPosition()
}

function handleResize() { scheduleComposerPosition() }

function handleGlobalKey(event) {
  if (event.key === 'Escape') {
    if (commentComposer.open) cancelComment()
    else dismissTransient()
    return
  }
  if (!props.open || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  if (event.target?.closest?.('input,textarea,select,button,[contenteditable="true"],.ant-select')) return
  if (event.key === 'ArrowLeft' && index.value > 0) { event.preventDefault(); index.value -= 1 }
  if (event.key === 'ArrowRight' && index.value < props.files.length - 1) { event.preventDefault(); index.value += 1 }
  if (event.key === 'ArrowUp' && props.targetIndex > 0) { event.preventDefault(); requestTarget(-1) }
  if (event.key === 'ArrowDown' && props.targetIndex < props.targets.length - 1) { event.preventDefault(); requestTarget(1) }
}

function deleteAnnotation(id) {
  const target = feedback.annotations.findIndex(item => item.id === id)
  if (target >= 0) feedback.annotations.splice(target, 1)
  if (selectedAnnotationId.value === id) selectedAnnotationId.value = ''
  if (commentComposer.annotationId === id) commentComposer.open = false
}

function feedbackPayload() {
  return {
    revision: feedback.revision,
    grade: feedback.grade,
    comment: feedback.comment || '',
    annotations: feedback.annotations.map(item => ({ id: /^[0-9a-f-]{36}$/i.test(item.id || '') ? item.id : null, file_id: item.file_id, kind: item.kind, mark_type: item.mark_type || (item.comment ? 'COMMENT' : 'HIGHLIGHT'), color: item.color || 'YELLOW', anchor: item.anchor, comment: item.comment || '' }))
  }
}

async function saveFeedback(publish) {
  if (!props.submissionVersionId) return
  if (!feedback.grade) { message.warning('请先选择作业等级'); return false }
  saving.value = true
  try {
    const peer = props.mode === 'PEER'
    const path = peer ? `/submission-versions/${props.submissionVersionId}/peer-feedback/publish` : `/submission-versions/${props.submissionVersionId}/feedback/${publish ? 'publish' : 'draft'}`
    const saved = await api(path, { method: peer || publish ? 'POST' : 'PUT', body: JSON.stringify(feedbackPayload()) })
    resetFeedback(saved)
    emit('feedback-published', saved.result)
    message.success(peer ? (saved.updated ? '互评已更新' : '互评已提交') : publish ? '教师反馈已发布' : '反馈草稿已保存')
    return true
  } catch (saveError) { message.error(saveError.message); return false }
  finally { saving.value = false }
}

async function requestTarget(offset) {
  const nextIndex = props.targetIndex + offset
  if (saving.value || nextIndex < 0 || nextIndex >= props.targets.length) return
  if (props.editable && JSON.stringify(feedbackPayload()) !== feedbackBaseline) {
    const saved = await saveFeedback(false)
    if (!saved) return
  }
  emit('target-change', nextIndex)
}

function annotationLabel(item) {
  if (item.kind === 'PDF_TEXT_OR_REGION') return item.anchor.quote || `第 ${item.anchor.page} 页区域`
  return item.anchor.exact || '文字选区'
}

watch(() => props.open, value => {
  document.documentElement.classList.toggle('file-preview-open', value)
  if (!value) { stopSpeechInput(); dismissTransient(); commentComposer.open = false; return }
  teacherAnnotationsExpanded.value = false
  peerAnnotationsExpanded.value = false
  index.value = Math.min(props.initialIndex, Math.max(0, props.files.length - 1))
  loadFeedback(); loadFile()
})
watch(index, () => { stopSpeechInput(); selectedAnnotationId.value = ''; commentComposer.open = false; dismissTransient(); loadFile() })
watch(() => props.files, () => { if (props.open) loadFile() }, { deep: true })
watch(() => props.submissionVersionId, () => {
  if (!props.open) return
  stopSpeechInput()
  index.value = 0
  loadFeedback(); loadFile()
})
onMounted(() => { document.addEventListener('pointerdown', handleGlobalPointer); document.addEventListener('scroll', handleGlobalScroll, true); document.addEventListener('keydown', handleGlobalKey); window.addEventListener('resize', handleResize) })
onBeforeUnmount(() => { stopSpeechInput(); loadSequence += 1; clearTimeout(drawerAnimationTimer); document.documentElement.classList.remove('file-preview-open'); if (positionFrame) cancelAnimationFrame(positionFrame); releaseBinaryUrl(); document.removeEventListener('pointerdown', handleGlobalPointer); document.removeEventListener('scroll', handleGlobalScroll, true); document.removeEventListener('keydown', handleGlobalKey); window.removeEventListener('resize', handleResize) })
</script>

<template>
  <a-drawer :open="open" :width="expanded?'100vw':'min(100vw, 1440px)'" :z-index="1200" placement="right" :root-class-name="expanded?'review-workspace-drawer expanded':'review-workspace-drawer'" @close="emit('close')">
    <template #title><div class="review-drawer-title"><span class="review-drawer-filename" :title="activeFile?.name||'文件预览'">{{activeFile?.name||'文件预览'}}</span><strong v-if="assignmentTitle" class="review-drawer-assignment" :title="assignmentTitle">{{assignmentTitle}}</strong><span/></div></template>
    <a-tooltip :open="drawerAnimating?false:undefined" :title="expanded?'收回':'展开至全屏'" placement="right"><button type="button" class="review-drawer-expand-button" :aria-label="expanded?'收回作业批改':'将作业批改展开至全屏'" @click="toggleExpanded"><RightOutlined v-if="expanded"/><ExpandOutlined v-else/></button></a-tooltip>
    <div class="review-workspace-toolbar">
      <a-space>
        <template v-if="hasTargetNavigation">
          <a-tooltip title="上一位学生（↑）"><span><a-button shape="circle" :disabled="targetIndex<=0||saving" @click="requestTarget(-1)"><ArrowUpOutlined/></a-button></span></a-tooltip>
          <strong class="review-target-progress">{{owner}} · {{targetIndex+1}} / {{targets.length}}</strong>
          <a-tooltip title="下一位学生（↓）"><span><a-button shape="circle" :disabled="targetIndex>=targets.length-1||saving" @click="requestTarget(1)"><ArrowDownOutlined/></a-button></span></a-tooltip>
          <span class="review-toolbar-divider"></span>
        </template>
        <a-tooltip title="上一个文件（←）"><span><a-button shape="circle" :disabled="index<=0" @click="index-=1"><LeftOutlined/></a-button></span></a-tooltip>
        <span>{{files.length ? `${index+1} / ${files.length}` : '0 / 0'}}</span>
        <a-tooltip title="下一个文件（→）"><span><a-button shape="circle" :disabled="index>=files.length-1" @click="index+=1"><RightOutlined/></a-button></span></a-tooltip>
        <a-select v-if="files.length>1" v-model:value="index" style="min-width:220px" :options="files.map((item,fileIndex)=>({value:fileIndex,label:fileOptionLabel(item)}))"/>
      </a-space>
      <div v-if="mode==='TEACHER'&&(visiblePeerFeedbacks.length||feedback.grade)" class="review-score-summary">
        <div v-if="visiblePeerFeedbacks.length" class="review-score-group peer-scores"><strong>学生互评</strong><a-tag v-for="peer in visiblePeerFeedbacks" :key="peer.id" color="purple">{{peer.evaluator_name}}打分 {{peer.grade}}</a-tag></div>
        <span v-if="visiblePeerFeedbacks.length&&feedback.grade" class="review-score-divider"></span>
        <div v-if="feedback.grade" class="review-score-group teacher-score"><strong>教师评分</strong><a-tag :color="feedback.status==='PUBLISHED'?'green':'gold'">{{feedback.grade}}</a-tag></div>
      </div>
      <a-button v-if="activeFile&&allowDownload" :href="`/api/v1/files/${activeFile.id}`"><DownloadOutlined/> 下载原文件</a-button>
    </div>
    <div ref="drawerRoot" class="file-review-workspace" :class="{'with-feedback':hasFeedbackPanel}">
      <main ref="documentStage" class="review-document-stage">
        <a-spin v-if="loading" size="large" tip="正在加载文件"/>
        <a-result v-else-if="error" status="warning" title="无法在线预览" :sub-title="error"><template #extra><a-button v-if="activeFile&&allowDownload" type="primary" :href="`/api/v1/files/${activeFile.id}`"><DownloadOutlined/> 下载原文件</a-button></template></a-result>
        <PdfDocumentViewer v-else-if="renderType==='PDF'&&binaryUrl" ref="documentViewer" :url="binaryUrl" :annotations="previewAnnotations" :editable="editable" :selected-annotation-id="selectedAnnotationId" @selection="handleSelection" @select="selectAnnotation" @layout="scheduleComposerPosition" @error="error=$event"/>
        <div v-else-if="renderType==='RICH_TEXT'&&richHtml" class="rich-document-scroll"><RichTextViewer ref="documentViewer" :html="richHtml" :annotations="previewAnnotations" :editable="editable" :selected-annotation-id="selectedAnnotationId" @selection="handleSelection" @select="selectAnnotation"/></div>
        <img v-else-if="renderType==='IMAGE'&&binaryUrl" class="review-image" :src="binaryUrl" :alt="activeFile?.name" @error="error='图片加载失败'"/>
      </main>
      <aside v-if="hasFeedbackPanel" class="feedback-sidebar">
        <a-alert v-if="externalWarning" type="warning" show-icon message="提交或评价数据已更新" description="当前未保存内容已保留。完成本次编辑后将自动同步最新数据。"/>
        <div class="feedback-heading"><div><strong>{{owner||'教师反馈'}}</strong><span v-if="feedback.status">{{feedback.status==='PUBLISHED'?'已发布':'草稿'}}<template v-if="feedback.has_draft"> · 有待发布修改</template></span></div><a-tag v-if="feedback.grade" :color="feedback.status==='PUBLISHED'?'green':'gold'">{{feedback.grade}}</a-tag></div>
        <template v-if="editable">
          <label class="feedback-field"><span>总评</span><RichTextEditor ref="overallEditor" v-model="feedback.comment" speech-enabled placeholder="填写整体评价"/></label>
        </template>
        <section class="annotation-section">
          <button type="button" class="annotation-section-heading collapsible-section-heading" :aria-expanded="teacherAnnotationsExpanded" @click="teacherAnnotationsExpanded=!teacherAnnotationsExpanded"><span><CaretRightOutlined :class="{expanded:teacherAnnotationsExpanded}"/><strong>{{mode==='TEACHER'?'教师文内批注':'文内批注'}}</strong></span><span>{{activeAnnotations.length}}</span></button>
          <a-empty v-if="teacherAnnotationsExpanded&&!activeAnnotations.length" :description="editable?'在文档中选中文字或框选区域添加批注':'暂无文内批注'"/>
          <article v-for="(annotation,annotationIndex) in teacherAnnotationsExpanded?activeAnnotations:[]" :key="annotation.id" class="annotation-item" :class="{active:selectedAnnotationId===annotation.id}" :data-sidebar-annotation-id="annotation.id" @click="selectAnnotation(annotation.id,(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT'))==='COMMENT')">
            <div class="annotation-item-heading"><span :title="annotationLabel(annotation)"><i class="annotation-color" :class="`color-${(annotation.color||'YELLOW').toLowerCase()}`"></i>{{annotationIndex+1}}. {{annotationLabel(annotation)}}</span><a-button v-if="editable" danger type="text" shape="circle" @click.stop="deleteAnnotation(annotation.id)"><DeleteOutlined/></a-button></div>
            <div class="annotation-meta">{{markTypes.find(item=>item.value===(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT')))?.label}}</div>
            <div v-if="annotation.comment" class="annotation-comment" v-html="annotation.comment"></div>
            <div v-if="editable&&selectedAnnotationId===annotation.id" class="annotation-item-actions" @click.stop>
              <a-select v-model:value="annotation.mark_type" size="small" :options="markTypeOptions(annotation)"/>
              <div class="inline-color-options"><button v-for="color in colors" :key="color.value" type="button" class="color-swatch" :class="[`color-${color.value.toLowerCase()}`,{active:annotation.color===color.value}]" :aria-label="color.label" @click="annotation.color=color.value"/></div>
              <a-button size="small" @click="addCommentToMark(annotation,$event)"><CommentOutlined/> {{annotation.comment?'编辑批注':'添加批注'}}</a-button>
            </div>
          </article>
        </section>
        <section v-if="mode==='TEACHER'&&peerFeedbackEnabled" class="peer-feedback-section">
          <button type="button" class="peer-feedback-heading collapsible-section-heading" :aria-expanded="peerAnnotationsExpanded" @click="peerAnnotationsExpanded=!peerAnnotationsExpanded"><div><CaretRightOutlined :class="{expanded:peerAnnotationsExpanded}"/><strong>学生互评</strong><span v-if="peerGrade">综合等级 {{peerGrade}}</span></div><a-tag color="purple">{{visiblePeerFeedbacks.length}} 人</a-tag></button>
          <a-empty v-if="peerAnnotationsExpanded&&!visiblePeerFeedbacks.length" image="simple" description="暂无学生互评"/>
          <article v-for="peer in peerAnnotationsExpanded?visiblePeerFeedbacks:[]" :key="peer.id" class="peer-feedback-card">
            <div class="peer-reviewer"><span><i class="peer-color-key"></i><strong>{{peer.evaluator_name}}</strong></span><a-tag color="purple">{{peer.grade}}</a-tag></div>
            <div v-if="peer.comment" class="peer-overall" v-html="peer.comment"></div>
            <div v-if="peer.annotations?.some(item=>item.file_id===activeFile?.id)" class="peer-annotation-list">
              <button v-for="(annotation,peerAnnotationIndex) in peer.annotations.filter(item=>item.file_id===activeFile?.id)" :key="annotation.id" type="button" :class="{active:selectedAnnotationId===annotation.id}" :data-sidebar-annotation-id="annotation.id" @click="selectAnnotation(annotation.id,(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT'))==='COMMENT')">
                <span>{{peerAnnotationIndex+1}}. {{annotationLabel(annotation)}}</span><small>{{annotation.comment?'查看批注':'查看标记'}}</small>
              </button>
            </div>
          </article>
        </section>
        <div v-if="!editable&&feedback.comment" class="published-overall"><strong>{{mode==='PEER'?'互评总评':'教师总评'}}</strong><div v-html="feedback.comment"></div></div>
        <div v-if="editable" class="feedback-actions">
          <div class="feedback-action-grade"><span>作业等级</span><div v-if="mode==='TEACHER'" class="feedback-grade-options" role="group" aria-label="作业等级"><button v-for="grade in ['A','B','C','D','E']" :key="grade" type="button" :class="{selected:feedback.grade===grade}" :aria-pressed="feedback.grade===grade" @click="feedback.grade=grade">{{grade}}</button></div><a-select v-else v-model:value="feedback.grade" placeholder="请选择等级" aria-label="作业等级" :options="['A','B','C','D','E'].map(value=>({value,label:value}))"/></div>
          <div class="feedback-action-buttons"><a-button v-if="mode==='TEACHER'&&feedback.status" danger @click="emit('clear-feedback')">清除反馈</a-button><a-button v-if="mode==='TEACHER'" :loading="saving" @click="saveFeedback(false)">保存草稿</a-button><a-button type="primary" :loading="saving" @click="saveFeedback(true)">{{mode==='PEER'?(feedback.status==='PUBLISHED'?'更新评价':'提交评价'):(feedback.status==='PUBLISHED'?'更新反馈':'发布')}}</a-button></div>
        </div>
      </aside>
    </div>
  </a-drawer>
  <Teleport to="body">
    <div v-if="selectionMenu.open" class="selection-action-menu" :style="{left:`${selectionMenu.left}px`,top:`${selectionMenu.top}px`}" @pointerdown.prevent>
      <a-tooltip title="高亮"><a-button type="text" shape="circle" @click="applyMark('HIGHLIGHT')"><HighlightOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="pendingSelection?.selectionType==='TEXT'" title="下划线"><a-button type="text" shape="circle" @click="applyMark('UNDERLINE')"><UnderlineOutlined/></a-button></a-tooltip>
      <a-tooltip v-if="pendingSelection?.selectionType==='TEXT'" title="删除线"><a-button type="text" shape="circle" @click="applyMark('STRIKETHROUGH')"><StrikethroughOutlined/></a-button></a-tooltip>
      <span class="selection-menu-divider"></span>
      <button v-for="color in colors" :key="color.value" type="button" class="color-swatch" :class="[`color-${color.value.toLowerCase()}`,{active:selectedColor===color.value}]" :aria-label="color.label" @click="selectedColor=color.value"/>
      <span class="selection-menu-divider"></span>
      <a-tooltip title="加批注"><a-button type="text" shape="circle" @click="openCommentComposer"><CommentOutlined/></a-button></a-tooltip>
    </div>
    <div v-if="commentComposer.open" class="annotation-composer" :class="{hidden:!commentComposer.visible}" :style="{left:`${commentComposer.left}px`,top:`${commentComposer.top}px`}" @pointerdown.stop @keydown.ctrl.enter.prevent="submitComment" @keydown.esc.stop.prevent="cancelComment">
      <template v-if="editable&&!selectedAnnotation?.readonly">
        <RichTextEditor ref="commentEditor" v-model="commentComposer.value" compact autofocus speech-enabled placeholder="输入批注内容"/>
        <div class="annotation-composer-actions"><span>Ctrl+Enter 提交</span><a-button size="small" @click="cancelComment">取消</a-button><a-button type="primary" size="small" @click="submitComment">{{commentComposer.mode==='new'?'添加批注':'保存修改'}}</a-button></div>
      </template>
      <template v-else>
        <div v-if="selectedAnnotation?.readonly" class="peer-comment-author"><i class="peer-color-key"></i>{{selectedAnnotation.evaluator_name}} · {{selectedAnnotation.peer_grade}}</div>
        <div class="annotation-readonly" v-html="commentComposer.value"></div>
        <div class="annotation-composer-actions"><span></span><a-button size="small" @click="cancelComment">关闭</a-button></div>
      </template>
    </div>
  </Teleport>
</template>

<style>
.review-workspace-drawer .ant-drawer-content-wrapper{transition:width .22s ease}.review-workspace-drawer .ant-drawer-header{padding:14px 20px}.review-drawer-title{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,1fr) minmax(0,1fr);align-items:center;gap:16px;width:100%}.review-drawer-filename,.review-drawer-assignment{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.review-drawer-assignment{color:#176b78;text-align:center}.review-workspace-drawer .ant-drawer-body{display:flex;min-height:0;flex-direction:column;padding:0;background:#e9edf1}.review-drawer-expand-button{position:absolute;z-index:10;top:50%;left:-16px;display:grid;width:32px;height:48px;padding:0;place-items:center;border:1px solid #d5dee7;border-radius:6px;background:#fff;color:#526579;box-shadow:0 3px 10px rgba(20,39,58,.14);font-size:15px;transform:translateY(-50%);cursor:pointer}.review-workspace-drawer.expanded .review-drawer-expand-button{left:8px}.review-drawer-expand-button:hover,.review-drawer-expand-button:focus-visible{border-color:#1677ff;color:#1677ff}.review-drawer-expand-button:focus-visible{outline:2px solid #91caff;outline-offset:2px}.review-workspace-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:58px;padding:9px 18px;border-bottom:1px solid #d9e1e8;background:#fff}.review-workspace-toolbar .ant-space>span{min-width:44px;color:#526579;text-align:center}.file-review-workspace{display:grid;min-height:0;flex:1;grid-template-columns:minmax(0,1fr)}.file-review-workspace.with-feedback{grid-template-columns:minmax(0,1fr) 400px}.review-document-stage{display:flex;min-width:0;min-height:0;align-items:center;justify-content:center;overflow:hidden}.review-document-stage>.ant-spin,.review-document-stage>.ant-result{padding:40px}.rich-document-scroll{width:100%;height:100%;overflow:auto;padding:24px}.review-image{display:block;max-width:100%;max-height:100%;object-fit:contain}.feedback-sidebar{display:flex;min-height:0;flex-direction:column;gap:15px;overflow:auto;padding:18px;border-left:1px solid #d7dfe7;background:#fff}.feedback-heading{display:flex;align-items:flex-start;justify-content:space-between}.feedback-heading strong,.feedback-heading span{display:block}.feedback-heading strong{color:#203448;font-size:15px}.feedback-heading span{margin-top:3px;color:#7b8998;font-size:12px}.feedback-field{display:grid;gap:7px;color:#45586c;font-size:13px}.annotation-section{display:grid;gap:10px}.annotation-section-heading{display:flex;justify-content:space-between;color:#31465a}.annotation-item{padding:10px;border:1px solid #e0e6eb;border-radius:6px;background:#fbfcfd;cursor:pointer}.annotation-item.active{border-color:#91caff;background:#f3f8fd}.annotation-item-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#41566a;font-size:12px}.annotation-item-heading>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.annotation-comment{margin-top:6px;color:#546779;font-size:13px;line-height:1.55}.annotation-comment p,.published-overall p{margin:0 0 6px}.published-overall{padding-top:14px;border-top:1px solid #e4e9ee;color:#526579}.published-overall>strong{display:block;margin-bottom:8px;color:#2b4055}.feedback-actions{position:sticky;bottom:-18px;z-index:6;display:grid;flex:0 0 auto;gap:10px;margin:auto -18px -18px;padding:12px 18px;border-top:1px solid #dce3e9;background:#fff;box-shadow:0 -5px 12px rgba(35,55,75,.08)}.feedback-action-grade{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:10px;color:#45586c;font-size:13px}.feedback-action-buttons{display:grid;grid-template-columns:repeat(auto-fit,minmax(94px,1fr));gap:8px}.feedback-action-buttons>.ant-btn{min-width:0;width:100%;padding-inline:10px}@media(max-width:900px){.review-drawer-title{grid-template-columns:minmax(0,1fr);gap:2px}.review-drawer-title>span:last-child{display:none}.review-drawer-assignment{text-align:left;font-size:12px}.file-review-workspace.with-feedback{grid-template-columns:1fr;grid-template-rows:minmax(420px,60vh) auto}.feedback-sidebar{border-top:1px solid #d7dfe7;border-left:0}.review-workspace-toolbar{align-items:stretch;flex-direction:column}.review-workspace-toolbar>.ant-btn{width:100%}.rich-document-scroll{padding:12px}}@media(max-width:760px){.review-drawer-expand-button{display:none}}
.review-workspace-toolbar{grid-template-columns:minmax(0,1fr) minmax(0,auto) minmax(0,1fr)}.review-workspace-toolbar>.ant-btn{justify-self:end}.review-score-summary{display:flex;min-width:0;max-width:min(50vw,760px);align-items:center;justify-content:center;gap:12px;padding:4px 12px}.review-score-group{display:flex;min-width:0;align-items:center;justify-content:center;gap:6px;flex-wrap:wrap}.review-score-group strong{flex:0 0 auto;color:#33475b;font-size:13px}.review-score-group .ant-tag{margin:0;font-weight:600}.review-score-divider{width:1px;height:28px;background:#d9e1e8}@media(max-width:1100px){.review-workspace-toolbar{display:flex;flex-wrap:wrap}.review-score-summary{order:3;width:100%;max-width:none;border-top:1px solid #edf0f2;padding-top:10px}.review-workspace-toolbar>.ant-btn{margin-left:auto}}@media(max-width:600px){.review-score-summary{align-items:stretch;flex-direction:column}.review-score-divider{width:100%;height:1px}.review-score-group{justify-content:flex-start}}
.annotation-meta{margin:4px 0 0 18px;color:#8a97a5;font-size:11px}.annotation-color{display:inline-block;width:10px;height:10px;margin-right:7px;border-radius:50%;background:var(--swatch)}.color-yellow{--swatch:#f6bd16}.color-green{--swatch:#52a339}.color-red{--swatch:#e24a4a}.color-blue{--swatch:#3182ce}.annotation-item-actions{display:grid;grid-template-columns:92px 1fr auto;align-items:center;gap:8px;margin-top:9px}.inline-color-options{display:flex;gap:5px}.color-swatch{width:18px;height:18px;padding:0;border:2px solid #fff;border-radius:50%;outline:1px solid #cbd5df;background:var(--swatch);cursor:pointer}.color-swatch.active{outline:2px solid #233f5d;outline-offset:1px}.selection-action-menu{position:fixed;z-index:1200;display:flex;align-items:center;gap:3px;padding:5px 7px;border:1px solid #d7dfe7;border-radius:6px;background:#fff;box-shadow:0 6px 20px rgba(25,43,62,.2)}.selection-menu-divider{width:1px;height:24px;margin:0 4px;background:#e0e6eb}.annotation-composer{position:fixed;z-index:1201;width:330px;padding:10px;border:1px solid #ccd7e1;border-radius:6px;background:#fff;box-shadow:0 8px 28px rgba(25,43,62,.24)}.annotation-composer-actions{display:flex;align-items:center;justify-content:flex-end;gap:7px;margin-top:8px}.annotation-composer-actions>span{margin-right:auto;color:#8a97a5;font-size:11px}.annotation-readonly{max-height:180px;overflow:auto;color:#3e5368;line-height:1.6}.annotation-readonly p{margin:0 0 7px}@media(max-width:600px){.annotation-composer{right:12px!important;left:12px!important;width:auto}.selection-action-menu{max-width:calc(100vw - 24px);overflow-x:auto}.annotation-item-actions{grid-template-columns:1fr}}
.file-review-workspace,.feedback-sidebar,.feedback-sidebar>*{min-width:0;max-width:100%}.feedback-sidebar{overflow-x:hidden;overflow-y:auto}.feedback-sidebar>.feedback-actions{max-width:none}.annotation-section,.annotation-item,.annotation-item-heading,.annotation-comment{min-width:0;max-width:100%}.annotation-item-heading>span{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.annotation-comment,.annotation-comment *,.published-overall,.published-overall *{max-width:100%;overflow-wrap:anywhere;word-break:break-word}.annotation-comment pre,.annotation-comment code,.published-overall pre,.published-overall code{white-space:pre-wrap}.annotation-comment img,.published-overall img{max-width:100%;height:auto}.annotation-item-actions{grid-template-columns:minmax(0,92px) minmax(0,1fr)}.annotation-item-actions>.ant-btn{grid-column:1/-1;width:100%}.feedback-actions{min-width:0}.feedback-action-buttons>.ant-btn{max-width:100%}
.review-drawer-expand-button{position:fixed;top:50dvh;right:calc(min(100vw,1440px) - 22px);left:auto;width:44px;height:44px;border:0;border-radius:0;background:transparent;box-shadow:none;clip-path:inset(0);transition:right .22s ease,clip-path .22s ease}
.review-drawer-expand-button::before{position:absolute;inset:6px;border:1px solid #d5dee7;border-radius:5px;background:#fff;box-shadow:0 3px 10px rgba(20,39,58,.14);transform:rotate(45deg);content:''}
.review-drawer-expand-button>.anticon{position:relative;z-index:1}
.review-workspace-drawer.expanded .review-drawer-expand-button{right:calc(100vw - 22px);left:auto;clip-path:inset(0 0 0 50%)}
.review-workspace-drawer.expanded .review-drawer-expand-button>.anticon{transform:translateX(11px)}
.review-drawer-expand-button:hover::before,.review-drawer-expand-button:focus-visible::before{border-color:#1677ff}
.review-drawer-expand-button:focus-visible{outline:0}
.review-drawer-expand-button:focus-visible::before{box-shadow:0 0 0 2px #91caff,0 3px 10px rgba(20,39,58,.14)}
.review-target-progress{max-width:220px;overflow:hidden;color:#31465a;text-overflow:ellipsis;white-space:nowrap}.review-toolbar-divider{width:1px;min-width:1px!important;height:28px;background:#d9e1e8}.annotation-composer{transition:opacity .14s ease,transform .14s ease}.annotation-composer.hidden{opacity:0;transform:translateY(4px);pointer-events:none}@media(prefers-reduced-motion:reduce){.annotation-composer{transition:none}}
.peer-feedback-section{display:grid;gap:10px;padding-top:15px;border-top:1px solid #e4e9ee}.peer-feedback-heading,.peer-reviewer{display:flex;align-items:center;justify-content:space-between;gap:10px}.peer-feedback-heading>div{display:flex;align-items:baseline;gap:8px}.peer-feedback-heading span{color:#7b8998;font-size:12px}.peer-feedback-card{padding:11px;border:1px solid #e3d5f2;border-left:3px solid #8b5cf6;border-radius:6px;background:#fcfaff}.peer-reviewer>span{display:flex;align-items:center;min-width:0;gap:7px;color:#33475b}.peer-color-key{display:inline-block;width:10px;height:10px;flex:0 0 auto;border-radius:50%;background:#8b5cf6}.peer-overall{margin-top:8px;color:#596a7c;font-size:13px;line-height:1.55}.peer-overall p{margin:0 0 5px}.peer-annotation-list{display:grid;gap:5px;margin-top:8px}.peer-annotation-list button{display:flex;min-width:0;align-items:center;justify-content:space-between;gap:8px;padding:6px 8px;border:1px solid #eadff5;border-radius:4px;color:#58466d;background:#fff;text-align:left;cursor:pointer}.peer-annotation-list button.active{border-color:#8b5cf6;background:#f4effb}.peer-annotation-list button span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.peer-annotation-list button small{flex:0 0 auto;color:#8a789e}.peer-comment-author{display:flex;align-items:center;gap:7px;margin-bottom:8px;color:#6d4c8b;font-size:12px;font-weight:600}
.collapsible-section-heading{width:100%;padding:4px 2px;border:0;border-radius:4px;background:transparent;color:#31465a;font:inherit;text-align:left;cursor:pointer}.collapsible-section-heading:hover{background:#f3f6f9}.collapsible-section-heading:focus-visible{outline:2px solid #91caff;outline-offset:2px}.collapsible-section-heading>span:first-child,.collapsible-section-heading>div{display:flex;align-items:center;gap:8px}.collapsible-section-heading .anticon{flex:0 0 auto;color:#8492a1;font-size:11px;transition:transform .18s}.collapsible-section-heading .anticon.expanded{transform:rotate(90deg)}.collapsible-section-heading .ant-tag{margin:0}
.feedback-grade-options{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;min-width:0}.feedback-grade-options>button{height:32px;min-width:0;padding:0;border:1px solid #d9d9d9;border-radius:6px;background:#fff;color:#45586c;font:inherit;cursor:pointer}.feedback-grade-options>button:hover{border-color:#1677ff;color:#1677ff}.feedback-grade-options>button.selected{border-color:#1677ff;background:#1677ff;color:#fff}.feedback-grade-options>button:focus-visible{outline:2px solid #91caff;outline-offset:2px}
</style>
