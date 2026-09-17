<script setup>
import { computed, ref, watch } from 'vue'
import { DeleteOutlined, DownloadOutlined, DownOutlined, FileTextOutlined, UpOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const props = defineProps({ files: { type: Array, default: () => [] }, assignmentId: String, canDelete: Boolean, deleting: Boolean })
const emit = defineEmits(['preview', 'delete', 'delete-selected'])
const expanded = ref(false)
const selectedIds = ref([])
const downloading = ref(false)
async function downloadSelected() {
  if (!selectedFiles.value.length || downloading.value) return
  downloading.value = true
  try {
    const query = new URLSearchParams()
    selectedFiles.value.forEach(file => query.append('file_ids',file.id))
    const response = await fetch(`/api/v1/assignments/${props.assignmentId}/materials.zip?${query}`, { credentials: 'include' })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.message || '批量下载失败')
    }
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'assignment-materials.zip'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url),60000)
  } catch (error) { message.error(error.message) }
  finally { downloading.value = false }
}
const selectedFiles = computed(() => props.files.filter(file => selectedIds.value.includes(file.id)))
const allSelected = computed(() => props.files.length>0&&selectedFiles.value.length===props.files.length)
function selectFile(id, checked) {
  selectedIds.value = checked ? [...selectedIds.value,id] : selectedIds.value.filter(item => item!==id)
}
function selectAll(checked) {
  selectedIds.value = checked ? props.files.map(file => file.id) : []
  if (checked) expanded.value = true
}
watch(() => props.files.map(file => file.id).join(','), () => {
  selectedIds.value = selectedIds.value.filter(id => props.files.some(file => file.id===id))
  if (props.files.length<=3) expanded.value = false
})
</script>

<template>
  <div class="assignment-materials">
    <div v-if="(canDelete||assignmentId)&&files.length" class="materials-selection">
      <label><input type="checkbox" :checked="allSelected" :indeterminate="selectedFiles.length>0&&!allSelected" :disabled="deleting" @change="selectAll($event.target.checked)"> 全选</label>
      <span v-if="selectedFiles.length">已选 {{selectedFiles.length}} 个</span>
      <a-button v-if="assignmentId" type="text" :disabled="!selectedFiles.length" :loading="downloading" @click="downloadSelected"><DownloadOutlined/> 下载所选</a-button>
      <a-button v-if="canDelete" danger type="text" :disabled="!selectedFiles.length||deleting" :loading="deleting" @click="emit('delete-selected',selectedFiles)"><DeleteOutlined/> 删除所选</a-button>
    </div>
    <div class="assignment-file-list" :class="{'materials-stacked':files.length>3&&!expanded}">
      <div v-for="file in (files.length>3&&!expanded ? files.slice(0,1) : files)" :key="file.id" class="assignment-file-row">
        <span class="materials-file-leading"><input v-if="canDelete||assignmentId" type="checkbox" :aria-label="`选择附件 ${file.name}`" :checked="selectedIds.includes(file.id)" :disabled="deleting" @change="selectFile(file.id,$event.target.checked)"><span class="assignment-file-icon"><FileTextOutlined/></span></span>
        <button type="button" class="file-preview-link" @click="emit('preview',file,files)">{{file.name}}<small v-if="file.download_only">（下载查看）</small></button>
        <a-space>
          <a-tooltip title="下载原文件"><a-button type="text" shape="circle" :href="`/api/v1/files/${file.id}`"><DownloadOutlined/></a-button></a-tooltip>
          <a-tooltip v-if="canDelete" title="删除附件"><a-button danger type="text" shape="circle" :disabled="deleting" @click="emit('delete',file)"><DeleteOutlined/></a-button></a-tooltip>
        </a-space>
      </div>
    </div>
    <div v-if="files.length>3" class="materials-toggle">
      <a-button type="text" :aria-expanded="expanded" @click="expanded=!expanded"><UpOutlined v-if="expanded"/><DownOutlined v-else/>{{expanded?'收起附件':`展开全部 ${files.length} 个附件`}}</a-button>
    </div>
  </div>
</template>

<style scoped>
.materials-selection{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:10px;color:#647589;font-size:13px}
.materials-selection label,.materials-file-leading{display:flex;align-items:center;gap:8px}
.materials-selection input,.materials-file-leading input{width:16px;height:16px;margin:0;flex-shrink:0;accent-color:#1769aa}
.materials-file-leading .assignment-file-icon{flex-shrink:0}
.assignment-materials:has(.materials-selection) .assignment-file-row{grid-template-columns:62px minmax(0,1fr) auto}
.materials-stacked{position:relative;isolation:isolate;margin-bottom:16px}
.materials-stacked::before,.materials-stacked::after{content:'';position:absolute;height:100%;border:1px solid #e3e9ef;border-radius:6px;background:#f4f7fa;z-index:-1;box-sizing:border-box}
.materials-stacked::before{inset:8px 8px auto}
.materials-stacked::after{inset:16px 16px auto;z-index:-2;background:#edf2f6}
.materials-toggle{display:flex;justify-content:center;margin-top:8px}
</style>
