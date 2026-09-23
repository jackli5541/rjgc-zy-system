import { api } from '../../../api'
import { message } from 'ant-design-vue'
import { reactive } from 'vue'

export function useRoster(ctx) {
  const importState = reactive({ file: null, preview: null, result: null, step: 0, loading: false })

  function chooseRoster(file) { importState.file = file; importState.preview = null; importState.result = null; importState.step = 0; return false }

  async function previewRoster() {
    if (!importState.file) return message.warning('请选择名单文件')
    importState.loading = true
    try { const body = new FormData(); body.append('file', importState.file); importState.preview = await api(`/classes/${ctx.classId.value}/members/import-preview`, { method: 'POST', body }); importState.step = 1 }
    catch (e) { message.error(e.message) } finally { importState.loading = false }
  }

  async function confirmRoster() {
    try {
      importState.loading = true
      importState.result = await api(`/classes/${ctx.classId.value}/members/import/${importState.preview.batch_id}/confirm`, { method: 'POST' })
      importState.step = 2; message.success(`已创建 ${importState.result.created} 个账号，加入 ${importState.result.joined} 名学生`)
      ctx.members.value = (await api(`/classes/${ctx.classId.value}/members`)).items
    } catch (e) { message.error(e.message) } finally { importState.loading = false }
  }

  function closeImport() { ctx.modals.import = false; Object.assign(importState, { file: null, preview: null, result: null, step: 0, loading: false }) }

  return { importState, chooseRoster, previewRoster, confirmRoster, closeImport }
}
