<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ArrowDownOutlined, ArrowUpOutlined, CommentOutlined, DeleteOutlined, DownloadOutlined, HighlightOutlined, LeftOutlined, RightOutlined, StrikethroughOutlined, UnderlineOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { api } from '../api'
import PdfDocumentViewer from './PdfDocumentViewer.vue'
import RichTextEditor from './RichTextEditor.vue'
import RichTextViewer from './RichTextViewer.vue'

const props = defineProps({
  open: Boolean,
  files: { type: Array, default: () => [] },
  initialIndex: { type: Number, default: 0 },
  submissionVersionId: { type: String, default: '' },
  owner: { type: String, default: '' },
  editable: Boolean,
  mode: { type: String, default: 'TEACHER' },
  targets: { type: Array, default: () => [] },
  targetIndex: { type: Number, default: 0 },
  initialFeedback: { type: Object, default: null }
})
const emit = defineEmits(['close', 'feedback-published', 'clear-feedback', 'target-change', 'external-target'])
const index = ref(0)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const richHtml = ref('')
const binaryUrl = ref('')
const selectedAnnotationId = ref('')
const pendingSelection = ref(null)
const selectedColor = ref('YELLOW')
const drawerRoot = ref(null)
const documentStage = ref(null)
const documentViewer = ref(null)
const selectionMenu = reactive({ open: false, left: 0, top: 0 })
const commentComposer = reactive({ open: false, visible: true, mode: 'new', annotationId: '', left: 0, top: 0, value: '' })
let loadSequence = 0
let positionFrame = 0
let feedbackBaseline = ''
const feedback = reactive({ status: null, revision: 0, grade: 'A', comment: '', annotations: [], published_at: null, has_draft: false })
const externalWarning = ref(false)

const activeFile = computed(() => props.files[index.value] || null)
const renderType = computed(() => activeFile.value?.render_type || (/\.pdf$/i.test(activeFile.value?.name || '') ? 'PDF' : /\.(md|html?)$/i.test(activeFile.value?.name || '') ? 'RICH_TEXT' : /\.(png|jpe?g|gif|webp)$/i.test(activeFile.value?.name || '') ? 'IMAGE' : 'DOWNLOAD_ONLY'))
const activeAnnotations = computed(() => feedback.annotations.filter(item => item.file_id === activeFile.value?.id))
const selectedAnnotation = computed(() => feedback.annotations.find(item => item.id === selectedAnnotationId.value) || null)
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
  Object.assign(feedback, { status: null, revision: 0, grade: 'A', comment: '', annotations: [], published_at: null, has_draft: false }, value, { revision: value.revision ?? value.version ?? 0 })
  feedback.annotations = (value.annotations || []).map(item => ({ ...item, mark_type: item.mark_type || (item.comment ? 'COMMENT' : 'HIGHLIGHT'), color: item.color || 'YELLOW' }))
  selectedAnnotationId.value = ''
  commentComposer.open = false
  dismissTransient()
  feedbackBaseline = JSON.stringify(feedbackPayload())
  externalWarning.value = false
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
    error.value = file.preview_error || '该文件格式暂不支持在线预览，可下载原文件查看。'
    return
  }
  loading.value = true
  try {
    if (renderType.value === 'RICH_TEXT') {
      const rendered = await api(`/files/${file.id}/render`)
      if (sequence === loadSequence) richHtml.value = rendered.html
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
  pendingSelection.value = { ...payload, fileId: activeFile.value?.id }
  commentComposer.open = false
  const position = selectionToolbarPosition(payload.viewportRect)
  Object.assign(selectionMenu, { open: true, ...position })
}

function addAnnotation(payload, markType, color, comment = '') {
  if (!props.editable || !payload.fileId) return null
  const annotation = { id: crypto.randomUUID(), file_id: payload.fileId, kind: payload.kind, mark_type: markType, color, anchor: payload.anchor, comment }
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
  commentComposer.open = false
  pendingSelection.value = null
  clearBrowserSelection()
}

function cancelComment() {
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
  requestAnimationFrame(() => drawerRoot.value?.querySelector(`.annotation-item[data-annotation-id="${id}"]`)?.scrollIntoView({ block: 'nearest' }))
  const annotation = feedback.annotations.find(item => item.id === id)
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
  if (!value) { dismissTransient(); commentComposer.open = false; return }
  index.value = Math.min(props.initialIndex, Math.max(0, props.files.length - 1))
  loadFeedback(); loadFile()
})
watch(index, () => { selectedAnnotationId.value = ''; commentComposer.open = false; dismissTransient(); loadFile() })
watch(() => props.files, () => { if (props.open) loadFile() }, { deep: true })
watch(() => props.submissionVersionId, () => {
  if (!props.open) return
  index.value = 0
  loadFeedback(); loadFile()
})
onMounted(() => { document.addEventListener('pointerdown', handleGlobalPointer); document.addEventListener('scroll', handleGlobalScroll, true); document.addEventListener('keydown', handleGlobalKey); window.addEventListener('resize', handleResize) })
onBeforeUnmount(() => { loadSequence += 1; if (positionFrame) cancelAnimationFrame(positionFrame); releaseBinaryUrl(); document.removeEventListener('pointerdown', handleGlobalPointer); document.removeEventListener('scroll', handleGlobalScroll, true); document.removeEventListener('keydown', handleGlobalKey); window.removeEventListener('resize', handleResize) })
</script>

<template>
  <a-drawer :open="open" :width="'min(100vw, 1440px)'" placement="right" root-class-name="review-workspace-drawer" :title="activeFile?.name||'文件预览'" @close="emit('close')">
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
      <a-button v-if="activeFile" :href="`/api/v1/files/${activeFile.id}`"><DownloadOutlined/> 下载原文件</a-button>
    </div>
    <div ref="drawerRoot" class="file-review-workspace" :class="{'with-feedback':hasFeedbackPanel}">
      <main ref="documentStage" class="review-document-stage">
        <a-spin v-if="loading" size="large" tip="正在加载文件"/>
        <a-result v-else-if="error" status="warning" title="无法在线预览" :sub-title="error"><template #extra><a-button v-if="activeFile" type="primary" :href="`/api/v1/files/${activeFile.id}`"><DownloadOutlined/> 下载原文件</a-button></template></a-result>
        <PdfDocumentViewer v-else-if="renderType==='PDF'&&binaryUrl" ref="documentViewer" :url="binaryUrl" :annotations="activeAnnotations" :editable="editable" :selected-annotation-id="selectedAnnotationId" @selection="handleSelection" @select="selectAnnotation" @layout="scheduleComposerPosition" @error="error=$event"/>
        <div v-else-if="renderType==='RICH_TEXT'&&richHtml" class="rich-document-scroll"><RichTextViewer ref="documentViewer" :html="richHtml" :annotations="activeAnnotations" :editable="editable" :selected-annotation-id="selectedAnnotationId" @selection="handleSelection" @select="selectAnnotation"/></div>
        <img v-else-if="renderType==='IMAGE'&&binaryUrl" class="review-image" :src="binaryUrl" :alt="activeFile?.name" @error="error='图片加载失败'"/>
      </main>
      <aside v-if="hasFeedbackPanel" class="feedback-sidebar">
        <a-alert v-if="externalWarning" type="warning" show-icon message="提交或评价数据已更新" description="当前未保存内容已保留。完成本次编辑后将自动同步最新数据。"/>
        <div class="feedback-heading"><div><strong>{{owner||'教师反馈'}}</strong><span v-if="feedback.status">{{feedback.status==='PUBLISHED'?'已发布':'草稿'}}<template v-if="feedback.has_draft"> · 有待发布修改</template></span></div><a-tag :color="feedback.status==='PUBLISHED'?'green':'gold'">{{feedback.grade}}</a-tag></div>
        <template v-if="editable">
          <label class="feedback-field"><span>作业等级</span><a-select v-model:value="feedback.grade" :options="['A','B','C','D','E'].map(value=>({value,label:value}))"/></label>
          <label class="feedback-field"><span>总评</span><RichTextEditor v-model="feedback.comment" placeholder="填写整体评价"/></label>
        </template>
        <section class="annotation-section">
          <div class="annotation-section-heading"><strong>文内批注</strong><span>{{activeAnnotations.length}}</span></div>
          <a-empty v-if="!activeAnnotations.length" :description="editable?'在文档中选中文字或框选区域添加批注':'暂无文内批注'"/>
          <article v-for="(annotation,annotationIndex) in activeAnnotations" :key="annotation.id" class="annotation-item" :class="{active:selectedAnnotationId===annotation.id}" :data-annotation-id="annotation.id" @click="selectAnnotation(annotation.id,(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT'))==='COMMENT')">
            <div class="annotation-item-heading"><span><i class="annotation-color" :class="`color-${(annotation.color||'YELLOW').toLowerCase()}`"></i>{{annotationIndex+1}}. {{annotationLabel(annotation)}}</span><a-button v-if="editable" danger type="text" shape="circle" @click.stop="deleteAnnotation(annotation.id)"><DeleteOutlined/></a-button></div>
            <div class="annotation-meta">{{markTypes.find(item=>item.value===(annotation.mark_type||(annotation.comment?'COMMENT':'HIGHLIGHT')))?.label}}</div>
            <div v-if="annotation.comment" class="annotation-comment" v-html="annotation.comment"></div>
            <div v-if="editable&&selectedAnnotationId===annotation.id" class="annotation-item-actions" @click.stop>
              <a-select v-model:value="annotation.mark_type" size="small" :options="markTypeOptions(annotation)"/>
              <div class="inline-color-options"><button v-for="color in colors" :key="color.value" type="button" class="color-swatch" :class="[`color-${color.value.toLowerCase()}`,{active:annotation.color===color.value}]" :aria-label="color.label" @click="annotation.color=color.value"/></div>
              <a-button size="small" @click="addCommentToMark(annotation,$event)"><CommentOutlined/> {{annotation.comment?'编辑批注':'添加批注'}}</a-button>
            </div>
          </article>
        </section>
        <div v-if="!editable&&feedback.comment" class="published-overall"><strong>{{mode==='PEER'?'互评总评':'教师总评'}}</strong><div v-html="feedback.comment"></div></div>
        <div v-if="editable" class="feedback-actions"><a-button v-if="mode==='TEACHER'&&feedback.status" danger @click="emit('clear-feedback')">清除反馈</a-button><span/><a-button v-if="mode==='TEACHER'" :loading="saving" @click="saveFeedback(false)">保存草稿</a-button><a-button type="primary" :loading="saving" @click="saveFeedback(true)">{{mode==='PEER'?(feedback.status==='PUBLISHED'?'更新评价':'提交评价'):(feedback.status==='PUBLISHED'?'更新反馈':'发布反馈')}}</a-button></div>
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
      <template v-if="editable">
        <RichTextEditor v-model="commentComposer.value" compact autofocus placeholder="输入批注内容"/>
        <div class="annotation-composer-actions"><span>Ctrl+Enter 提交</span><a-button size="small" @click="cancelComment">取消</a-button><a-button type="primary" size="small" @click="submitComment">{{commentComposer.mode==='new'?'添加批注':'保存修改'}}</a-button></div>
      </template>
      <template v-else>
        <div class="annotation-readonly" v-html="commentComposer.value"></div>
        <div class="annotation-composer-actions"><span></span><a-button size="small" @click="cancelComment">关闭</a-button></div>
      </template>
    </div>
  </Teleport>
</template>

<style>
.review-workspace-drawer .ant-drawer-header{padding:14px 20px}.review-workspace-drawer .ant-drawer-body{display:flex;min-height:0;flex-direction:column;padding:0;background:#e9edf1}.review-workspace-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:58px;padding:9px 18px;border-bottom:1px solid #d9e1e8;background:#fff}.review-workspace-toolbar .ant-space>span{min-width:44px;color:#526579;text-align:center}.file-review-workspace{display:grid;min-height:0;flex:1;grid-template-columns:minmax(0,1fr)}.file-review-workspace.with-feedback{grid-template-columns:minmax(0,1fr) 360px}.review-document-stage{display:flex;min-width:0;min-height:0;align-items:center;justify-content:center;overflow:hidden}.review-document-stage>.ant-spin,.review-document-stage>.ant-result{padding:40px}.rich-document-scroll{width:100%;height:100%;overflow:auto;padding:24px}.review-image{display:block;max-width:100%;max-height:100%;object-fit:contain}.feedback-sidebar{display:flex;min-height:0;flex-direction:column;gap:15px;overflow:auto;padding:18px;border-left:1px solid #d7dfe7;background:#fff}.feedback-heading{display:flex;align-items:flex-start;justify-content:space-between}.feedback-heading strong,.feedback-heading span{display:block}.feedback-heading strong{color:#203448;font-size:15px}.feedback-heading span{margin-top:3px;color:#7b8998;font-size:12px}.feedback-field{display:grid;gap:7px;color:#45586c;font-size:13px}.annotation-section{display:grid;gap:10px}.annotation-section-heading{display:flex;justify-content:space-between;color:#31465a}.annotation-item{padding:10px;border:1px solid #e0e6eb;border-radius:6px;background:#fbfcfd;cursor:pointer}.annotation-item.active{border-color:#91caff;background:#f3f8fd}.annotation-item-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;color:#41566a;font-size:12px}.annotation-item-heading>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.annotation-comment{margin-top:6px;color:#546779;font-size:13px;line-height:1.55}.annotation-comment p,.published-overall p{margin:0 0 6px}.published-overall{padding-top:14px;border-top:1px solid #e4e9ee;color:#526579}.published-overall>strong{display:block;margin-bottom:8px;color:#2b4055}.feedback-actions{position:sticky;bottom:-18px;display:grid;grid-template-columns:auto 1fr auto auto;gap:8px;margin:0 -18px -18px;padding:12px 18px;border-top:1px solid #dce3e9;background:#fff}@media(max-width:900px){.file-review-workspace.with-feedback{grid-template-columns:1fr;grid-template-rows:minmax(420px,60vh) auto}.feedback-sidebar{border-top:1px solid #d7dfe7;border-left:0}.review-workspace-toolbar{align-items:stretch;flex-direction:column}.review-workspace-toolbar>.ant-btn{width:100%}.rich-document-scroll{padding:12px}}
.annotation-meta{margin:4px 0 0 18px;color:#8a97a5;font-size:11px}.annotation-color{display:inline-block;width:10px;height:10px;margin-right:7px;border-radius:50%;background:var(--swatch)}.color-yellow{--swatch:#f6bd16}.color-green{--swatch:#52a339}.color-red{--swatch:#e24a4a}.color-blue{--swatch:#3182ce}.annotation-item-actions{display:grid;grid-template-columns:92px 1fr auto;align-items:center;gap:8px;margin-top:9px}.inline-color-options{display:flex;gap:5px}.color-swatch{width:18px;height:18px;padding:0;border:2px solid #fff;border-radius:50%;outline:1px solid #cbd5df;background:var(--swatch);cursor:pointer}.color-swatch.active{outline:2px solid #233f5d;outline-offset:1px}.selection-action-menu{position:fixed;z-index:1200;display:flex;align-items:center;gap:3px;padding:5px 7px;border:1px solid #d7dfe7;border-radius:6px;background:#fff;box-shadow:0 6px 20px rgba(25,43,62,.2)}.selection-menu-divider{width:1px;height:24px;margin:0 4px;background:#e0e6eb}.annotation-composer{position:fixed;z-index:1201;width:330px;padding:10px;border:1px solid #ccd7e1;border-radius:6px;background:#fff;box-shadow:0 8px 28px rgba(25,43,62,.24)}.annotation-composer-actions{display:flex;align-items:center;justify-content:flex-end;gap:7px;margin-top:8px}.annotation-composer-actions>span{margin-right:auto;color:#8a97a5;font-size:11px}.annotation-readonly{max-height:180px;overflow:auto;color:#3e5368;line-height:1.6}.annotation-readonly p{margin:0 0 7px}@media(max-width:600px){.annotation-composer{right:12px!important;left:12px!important;width:auto}.selection-action-menu{max-width:calc(100vw - 24px);overflow-x:auto}.annotation-item-actions{grid-template-columns:1fr}}
.file-review-workspace,.feedback-sidebar,.feedback-sidebar>*{min-width:0;max-width:100%}.feedback-sidebar{overflow-x:hidden;overflow-y:auto}.annotation-section,.annotation-item,.annotation-item-heading,.annotation-comment{min-width:0;max-width:100%}.annotation-item-heading>span{min-width:0;flex:1;white-space:normal;overflow-wrap:anywhere;word-break:break-word}.annotation-comment,.annotation-comment *,.published-overall,.published-overall *{max-width:100%;overflow-wrap:anywhere;word-break:break-word}.annotation-comment pre,.annotation-comment code,.published-overall pre,.published-overall code{white-space:pre-wrap}.annotation-comment img,.published-overall img{max-width:100%;height:auto}.annotation-item-actions{grid-template-columns:minmax(0,92px) minmax(0,1fr)}.annotation-item-actions>.ant-btn{grid-column:1/-1;width:100%}.feedback-actions{display:flex;min-width:0;flex-wrap:wrap}.feedback-actions>span{min-width:0;flex:1}.feedback-actions>.ant-btn{max-width:100%}
.review-target-progress{max-width:220px;overflow:hidden;color:#31465a;text-overflow:ellipsis;white-space:nowrap}.review-toolbar-divider{width:1px;min-width:1px!important;height:28px;background:#d9e1e8}.annotation-composer{transition:opacity .14s ease,transform .14s ease}.annotation-composer.hidden{opacity:0;transform:translateY(4px);pointer-events:none}@media(prefers-reduced-motion:reduce){.annotation-composer{transition:none}}
</style>
