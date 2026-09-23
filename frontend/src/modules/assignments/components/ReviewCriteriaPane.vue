<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ColumnWidthOutlined, LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons-vue'
import { api } from '../../../api'
import { loadMarkdownPreview } from '../../../markdownPreview'
import PdfDocumentViewer from '../../../shared/components/PdfDocumentViewer.vue'
import RichTextViewer from '../../../shared/components/RichTextViewer.vue'

const props = defineProps({ files: { type: Array, default: () => [] } })
const index = ref(0)
const zoom = ref(1)
const loading = ref(false)
const error = ref('')
const richHtml = ref('')
const binaryUrl = ref('')
let loadSequence = 0

const activeFile = computed(() => props.files[index.value] || null)
const renderType = computed(() => activeFile.value?.render_type || (/\.pdf$/i.test(activeFile.value?.name || '') ? 'PDF' : /\.(md|html?)$/i.test(activeFile.value?.name || '') ? 'RICH_TEXT' : /\.(png|jpe?g|gif|webp)$/i.test(activeFile.value?.name || '') ? 'IMAGE' : 'DOWNLOAD_ONLY'))

function releaseBinaryUrl() {
  if (binaryUrl.value?.startsWith('blob:')) URL.revokeObjectURL(binaryUrl.value)
  binaryUrl.value = ''
}

async function loadFile() {
  const sequence = ++loadSequence
  releaseBinaryUrl(); richHtml.value = ''; error.value = ''; zoom.value = 1
  const file = activeFile.value
  if (!file) return
  if (!file.previewable || file.download_only || renderType.value === 'DOWNLOAD_ONLY') {
    error.value = file.preview_error || '该标准文件暂不支持在线预览。'
    return
  }
  loading.value = true
  try {
    if (renderType.value === 'RICH_TEXT') {
      if (!/\.md$/i.test(file.name || '')) throw new Error('仅支持 Markdown 文档在线预览')
      const { url } = await api(`/files/${file.id}/preview-url`)
      const html = await loadMarkdownPreview(url)
      if (sequence === loadSequence) richHtml.value = html
    } else if (renderType.value === 'IMAGE') {
      const response = await fetch(`/api/v1/files/${file.id}/preview`, { credentials: 'include' })
      if (!response.ok) throw new Error('图片加载失败')
      const url = URL.createObjectURL(await response.blob())
      if (sequence === loadSequence) binaryUrl.value = url
      else URL.revokeObjectURL(url)
    } else binaryUrl.value = `/api/v1/files/${file.id}/preview`
  } catch (loadError) { if (sequence === loadSequence) error.value = loadError.message || '标准文件加载失败' }
  finally { if (sequence === loadSequence) loading.value = false }
}

watch(index, loadFile)
watch(() => props.files, () => { index.value = Math.min(index.value, Math.max(0, props.files.length - 1)); loadFile() }, { deep: true, immediate: true })
onBeforeUnmount(() => { loadSequence += 1; releaseBinaryUrl() })
</script>

<template>
  <section class="criteria-preview-pane">
    <header class="criteria-preview-toolbar">
      <strong>互评标准</strong>
      <a-tooltip title="上一个标准文件"><span><a-button shape="circle" :disabled="index<=0" @click="index-=1"><LeftOutlined/></a-button></span></a-tooltip>
      <span>{{files.length ? `${index+1} / ${files.length}` : '0 / 0'}}</span>
      <a-tooltip title="下一个标准文件"><span><a-button shape="circle" :disabled="index>=files.length-1" @click="index+=1"><RightOutlined/></a-button></span></a-tooltip>
      <a-select v-if="files.length>1" v-model:value="index" :options="files.map((file,fileIndex)=>({value:fileIndex,label:file.name}))"/>
      <template v-if="renderType!=='PDF'">
        <i></i>
        <a-tooltip title="缩小标准"><a-button shape="circle" :disabled="zoom<=.6" @click="zoom=Math.max(.6,zoom-.1)"><ZoomOutOutlined/></a-button></a-tooltip>
        <span>{{Math.round(zoom*100)}}%</span>
        <a-tooltip title="放大标准"><a-button shape="circle" :disabled="zoom>=2" @click="zoom=Math.min(2,zoom+.1)"><ZoomInOutlined/></a-button></a-tooltip>
        <a-tooltip title="恢复标准大小"><a-button shape="circle" @click="zoom=1"><ColumnWidthOutlined/></a-button></a-tooltip>
      </template>
    </header>
    <div class="criteria-preview-stage">
      <a-spin v-if="loading" size="large" tip="正在加载互评标准"/>
      <a-result v-else-if="error" status="warning" title="无法在线预览" :sub-title="error"/>
      <PdfDocumentViewer v-else-if="renderType==='PDF'&&binaryUrl" :url="binaryUrl"/>
      <div v-else-if="renderType==='RICH_TEXT'&&richHtml" class="criteria-rich-scroll"><div :style="{zoom:`${zoom*100}%`}"><RichTextViewer :html="richHtml"/></div></div>
      <div v-else-if="renderType==='IMAGE'&&binaryUrl" class="criteria-image-scroll"><img :style="{width:`${zoom*100}%`}" :src="binaryUrl" :alt="activeFile?.name" @error="error='图片加载失败'"/></div>
    </div>
  </section>
</template>

<style scoped>
.criteria-preview-pane{display:flex;min-width:0;min-height:0;flex-direction:column;border-left:1px solid #d7dfe7;background:#e9edf1}.criteria-preview-toolbar{display:flex;min-height:52px;align-items:center;gap:7px;padding:7px 10px;border-bottom:1px solid #d9e1e8;background:#fff}.criteria-preview-toolbar strong{margin-right:auto;color:#31465a;font-size:13px}.criteria-preview-toolbar>span{min-width:36px;color:#526579;text-align:center}.criteria-preview-toolbar>.ant-select{width:150px}.criteria-preview-toolbar>i{width:1px;height:26px;background:#d9e1e8}.criteria-preview-stage{display:flex;min-width:0;min-height:0;flex:1;align-items:center;justify-content:center;overflow:hidden}.criteria-rich-scroll,.criteria-image-scroll{width:100%;height:100%;overflow:auto;padding:18px}.criteria-rich-scroll>div{transform-origin:top left}.criteria-image-scroll img{display:block;max-width:none;height:auto;margin:auto}.criteria-preview-stage>.ant-spin,.criteria-preview-stage>.ant-result{padding:30px}@media(max-width:760px){.criteria-preview-toolbar{flex-wrap:wrap}.criteria-preview-toolbar>.ant-select{width:100%}.criteria-rich-scroll,.criteria-image-scroll{padding:12px}}
</style>
