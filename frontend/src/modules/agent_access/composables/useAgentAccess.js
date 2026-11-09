import { api } from '../../../api'
import { computed, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'

export const AGENT_SCOPE_LABELS = { 'assignment:read': '作业-读', 'submission:read': '提交-读' }

export function useAgentAccess(ctx) {
  const agentTokens = ref([])
  const agentCalls = ref([])
  const agentTab = ref('tokens')
  const agentTokenModal = reactive({ open: false, editing: null })
  const agentTokenForm = reactive({ name: '', scopes: ['assignment:read', 'submission:read'], class_ids: [], expose_real_name: true, expires_days: 90, renew: false })
  const agentCreatedToken = ref('')
  const agentGuideOpen = ref(false)
  const importState = reactive({ classId: undefined, assignmentId: undefined, assignments: [], file: null, loading: false, report: null, overwrite: [], result: null })
  const agentEndpoint = computed(() => `${window.location.origin}/mcp`)
  const agentScopeOptions = Object.entries(AGENT_SCOPE_LABELS).map(([value, label]) => ({ value, label }))
  const agentClassOptions = computed(() => ctx.session.classes.map(item => ({ value: item.id, label: `${item.semester} · ${item.name}` })))

  async function loadAgentAccessView(isCurrent = () => true) {
    const [tokens, calls] = await Promise.all([api('/agent-tokens'), api('/agent-calls?limit=100')])
    if (!isCurrent()) return
    agentTokens.value = tokens.items
    agentCalls.value = calls.items
  }

  function resetImport() {
    importState.file = null
    importState.report = null
    importState.overwrite = []
    importState.result = null
  }

  async function loadImportAssignments(classId) {
    importState.classId = classId
    importState.assignmentId = undefined
    importState.assignments = []
    resetImport()
    if (!classId) return
    const data = await api(`/assignments?class_id=${classId}`)
    importState.assignments = data.items.filter(item => item.submitter_type === 'INDIVIDUAL' && item.status !== 'DRAFT').map(item => ({ value: item.id, label: item.title }))
  }

  function pickImportFile(file) {
    importState.file = file
    importState.report = null
    importState.result = null
    return false
  }

  async function previewImport() {
    if (!importState.assignmentId || !importState.file) { message.warning('请先选择作业并上传 Excel'); return }
    importState.loading = true
    try {
      const body = new FormData()
      body.append('file', importState.file)
      importState.report = await api(`/agent/imports/preview?assignment_id=${importState.assignmentId}`, { method: 'POST', body })
      importState.overwrite = []
      importState.result = null
    } catch (error) {
      message.error(error.message || '预览失败')
    } finally {
      importState.loading = false
    }
  }

  async function confirmImport() {
    const report = importState.report
    if (!report) return
    importState.loading = true
    try {
      importState.result = await api(`/agent/imports/${report.batch_id}/confirm`, { method: 'POST', body: JSON.stringify({ overwrite_version_ids: importState.overwrite }) })
      importState.report = null
      importState.file = null
      message.success('导入完成')
    } catch (error) {
      message.error(error.message || '导入失败')
    } finally {
      importState.loading = false
    }
  }

  function openAgentTokenForm(record = null) {
    agentTokenModal.editing = record
    Object.assign(agentTokenForm, record
      ? { name: record.name, scopes: [...record.scopes], class_ids: [...record.class_ids], expose_real_name: record.expose_real_name, expires_days: 90, renew: false }
      : { name: '', scopes: ['assignment:read', 'submission:read'], class_ids: [], expose_real_name: true, expires_days: 90, renew: false })
    agentTokenModal.open = true
  }

  async function saveAgentToken() {
    if (!agentTokenForm.name.trim()) { message.warning('请填写令牌名称'); return }
    if (!agentTokenForm.scopes.length) { message.warning('至少选择一项权限范围'); return }
    const editing = agentTokenModal.editing
    const body = { name: agentTokenForm.name, scopes: agentTokenForm.scopes, class_ids: agentTokenForm.class_ids, expose_real_name: agentTokenForm.expose_real_name }
    await ctx.action(async () => {
      if (editing) {
        await api(`/agent-tokens/${editing.id}`, { method: 'PUT', body: JSON.stringify({ ...body, expires_days: agentTokenForm.renew ? agentTokenForm.expires_days : null }) })
      } else {
        const created = await api('/agent-tokens', { method: 'POST', body: JSON.stringify({ ...body, expires_days: agentTokenForm.expires_days }) })
        agentCreatedToken.value = created.token
      }
      agentTokenModal.open = false
    }, editing ? '令牌已更新' : '令牌已创建')
  }

  async function revokeAgentToken(record) {
    await ctx.action(() => api(`/agent-tokens/${record.id}/revoke`, { method: 'POST' }), '令牌已吊销')
  }

  async function copyAgentText(text, tip = '已复制') {
    try {
      if (!window.isSecureContext || !navigator.clipboard) throw new Error('insecure')
      await navigator.clipboard.writeText(text)
      message.success(tip)
      return
    } catch (_) {
      // HTTP 站点没有 clipboard API，退回到 execCommand。
    }
    const box = document.createElement('textarea')
    box.value = text
    box.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
    document.body.appendChild(box)
    box.select()
    let copied = false
    try { copied = document.execCommand('copy') } catch (_) { copied = false }
    document.body.removeChild(box)
    if (copied) message.success(tip)
    else message.error('复制失败，请手动选择文本复制')
  }

  function agentConfigExample(token = '<粘贴你的令牌>') {
    return JSON.stringify({ mcpServers: { 'se-lab-grading': { type: 'streamable-http', url: agentEndpoint.value, headers: { Authorization: `Bearer ${token}` } } } }, null, 2)
  }

  const agentPromptExample = '请先调用 get_workflow_guide 读取批改流程，然后对作业《（填写作业名称）》逐个学生批改：读取评分标准和学生提交，对作业点评、对互评做二次点评、给出教师等级，把结果写入本地 Excel（如果我给了平台下载的模板，就填在模板里）。全部学生处理完后汇报。'

  return {
    agentTokens, agentCalls, agentTab, agentTokenModal, agentTokenForm, agentCreatedToken, agentGuideOpen, agentEndpoint,
    agentScopeOptions, agentClassOptions, loadAgentAccessView, openAgentTokenForm, saveAgentToken, revokeAgentToken, copyAgentText,
    agentConfigExample, agentPromptExample, importState, loadImportAssignments, pickImportFile, previewImport, confirmImport, resetImport,
  }
}
