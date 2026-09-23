import { api, exportArchive } from '../../../api'
import StarterKit from '@tiptap/starter-kit'
import { useEditor } from '@tiptap/vue-3'
import { Modal, message } from 'ant-design-vue'
import { computed, reactive, ref } from 'vue'

export function useAssignments(ctx) {
  const assignments = ref([])

  const assignmentForm = reactive({ id: '', version: 1, has_submissions: false, class_ids: [], title: '', description: '', submitter_type: 'INDIVIDUAL', kind: 'ASSIGNMENT', starts_at: '', due_at: '', allow_late: false, publish: true, auto_review_enabled: false, auto_review_mode: 'TEAM', auto_review_criteria_text: '', auto_review_due_at: '' })

  const descriptionEditor = useEditor({
    content: '',
    extensions: [StarterKit.configure({ link: { openOnClick: false } })],
    onUpdate: ({ editor }) => { assignmentForm.description = editor.getHTML() }
  })

  const materialTypeOptions = [{ label: '任务型', value: 'TASK', color: 'blue' }, { label: '附件型', value: 'ATTACHMENT' }, { label: '判定标准', value: 'CRITERIA', color: 'gold' }]

  const uploadMaterialType = ref('ATTACHMENT')

  const pendingAssignmentFiles = ref([])

  const assignmentAttachments = ref([])

  const reviewCriteriaFiles = ref([])

  const draftFiles = ref([])

  const deletingMaterials = ref(false)

  const exportingAssignment = ref(false)

  const studentPendingAssignments = computed(() => assignments.value.filter(item => item.status === 'PUBLISHED' && item.submission_status !== 'SUBMITTED'))

  const studentUpcomingAssignments = computed(() => {
    const limit = Date.now() + 72 * 60 * 60 * 1000
    return studentPendingAssignments.value.filter(item => new Date(item.due_at).getTime() <= limit && new Date(item.due_at).getTime() >= Date.now())
  })

  const studentCriteriaMaterials = computed(() => assignmentAttachments.value.filter(file => file.material_type === 'CRITERIA'))

  const gradingCriteriaFiles = computed(() => {
    const files = [...reviewCriteriaFiles.value]
    for (const file of assignmentAttachments.value.filter(item => item.material_type === 'CRITERIA')) {
      if (!files.some(item => item.id === file.id)) files.push(file)
    }
    return files
  })

  function openAssignmentCreate() {
    Object.assign(assignmentForm, { id: '', version: 1, has_submissions: false, class_ids: ctx.defaultClassSelection(), title: '', description: '', submitter_type: 'INDIVIDUAL', kind: 'ASSIGNMENT', starts_at: '', due_at: '', allow_late: false, publish: false, auto_review_enabled: false, auto_review_mode: 'TEAM', auto_review_criteria_text: '', auto_review_due_at: '' }); pendingAssignmentFiles.value = []; descriptionEditor.value?.commands.setContent('', { emitUpdate: false }); ctx.modals.assignment = true
  }

  function openAssignmentEdit() {
    const item = ctx.selectedAssignment.value
    Object.assign(assignmentForm, { id: item.id, version: item.version, has_submissions: (item.board || []).some(record => record.status === 'SUBMITTED'), class_ids: [item.class_id], title: item.title, description: item.description, submitter_type: item.submitter_type, kind: item.kind || 'ASSIGNMENT', starts_at: ctx.localDateTime(item.starts_at), due_at: ctx.localDateTime(item.due_at), allow_late: item.allow_late, publish: item.status === 'PUBLISHED', auto_review_enabled: item.auto_review_enabled, auto_review_mode: item.auto_review_mode || 'TEAM', auto_review_criteria_text: item.auto_review_criteria_text || '', auto_review_due_at: ctx.localDateTime(item.auto_review_due_at) })
    descriptionEditor.value?.commands.setContent(item.description || '', { emitUpdate: false }); pendingAssignmentFiles.value = []; ctx.modals.assignment = true
  }

  function setDescriptionLink() {
    const current = descriptionEditor.value?.getAttributes('link').href || ''
    const href = window.prompt('链接地址', current)
    if (href === null) return
    if (!href.trim()) descriptionEditor.value?.chain().focus().unsetLink().run()
    else descriptionEditor.value?.chain().focus().extendMarkRange('link').setLink({ href: href.trim() }).run()
  }

  function materialTypeOption(value) { return materialTypeOptions.find(option => option.value === value) || materialTypeOptions[1] }

  function queueAssignmentAttachment(file, materialType) { pendingAssignmentFiles.value.push({ file, materialType }); return false }

  function removePendingAssignmentAttachment(index) { pendingAssignmentFiles.value.splice(index, 1) }

  async function copyAssignmentFiles(targets) {
    const files = [
      ...assignmentAttachments.value.map(file => ({ ...file, purpose: 'ATTACHMENT' })),
      ...reviewCriteriaFiles.value.map(file => ({ ...file, purpose: 'REVIEW_CRITERIA' }))
    ]
    for (const file of files) {
      const response = await fetch(`/api/v1/files/${file.id}`, { credentials: 'include' })
      if (!response.ok) throw new Error(`复制附件“${file.name}”失败`)
      const blob = await response.blob()
      for (const target of targets) {
        const query = new URLSearchParams({ purpose: file.purpose })
        if (file.purpose === 'ATTACHMENT' && file.material_type) query.set('material_type', file.material_type)
        const body = new FormData()
        body.append('file', blob, file.name)
        await api(`/assignments/${target.id}/files?${query}`, { method: 'POST', body })
      }
    }
  }

  async function uploadPendingAssignmentFiles(targets, sourceId = '') {
    for (const target of targets) {
      for (const pending of pendingAssignmentFiles.value) {
        const body = new FormData(); body.append('file', pending.file)
        const attachment = await api(`/assignments/${target.id}/files?material_type=${pending.materialType}`, { method: 'POST', body })
        if (target.id === sourceId) assignmentAttachments.value.push(attachment)
      }
    }
    pendingAssignmentFiles.value = []
  }

  async function createAssignment(publishRequested = false) {
    if (!assignmentForm.class_ids.length) return message.warning('请至少选择一个教学班')
    if (assignmentForm.title.trim().length < 2) return message.warning('标题至少填写 2 个字符')
    const descriptionText = descriptionEditor.value?.getText().trim() || ''
    if (!descriptionText) return message.warning('请填写作业说明')
    if (!assignmentForm.due_at) return message.warning('请选择截止时间')
    if (assignmentForm.submitter_type === 'TEAM' && new Date(assignmentForm.due_at) <= new Date() && (publishRequested || (assignmentForm.id && ctx.selectedAssignment.value?.status === 'PUBLISHED'))) return message.warning('小组作业截止时间必须晚于当前时间')
    if (assignmentForm.starts_at && new Date(assignmentForm.starts_at) >= new Date(assignmentForm.due_at)) return message.warning('开始时间必须早于截止时间')
    if (assignmentForm.auto_review_enabled) {
      if (!assignmentForm.auto_review_due_at || new Date(assignmentForm.auto_review_due_at) <= new Date(assignmentForm.due_at)) return message.warning('互评截止时间必须晚于作业截止时间')
      if (!assignmentForm.auto_review_criteria_text.trim() && (!assignmentForm.id || !reviewCriteriaFiles.value.length)) return message.warning('自动互评标准文字和附件至少提供一种')
    }
    if (assignmentForm.id) {
      await ctx.action(async () => {
        const originalClassId = ctx.selectedAssignment.value.class_id
        const targetClassId = assignmentForm.class_ids.includes(originalClassId) ? originalClassId : assignmentForm.class_ids[0]
        const additionalClassIds = assignmentForm.class_ids.filter(id => id !== targetClassId)
        const payload = { class_id: targetClassId, title: assignmentForm.title, description: assignmentForm.description, submitter_type: assignmentForm.submitter_type, kind: assignmentForm.kind, starts_at: ctx.iso(assignmentForm.starts_at), due_at: ctx.iso(assignmentForm.due_at), allow_late: assignmentForm.allow_late, version: assignmentForm.version }
        if (ctx.reviewConfigEditable.value) Object.assign(payload, { auto_review_enabled: assignmentForm.auto_review_enabled, auto_review_mode: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_mode : null, auto_review_criteria_text: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_criteria_text : '', auto_review_due_at: assignmentForm.auto_review_enabled ? ctx.iso(assignmentForm.auto_review_due_at) : null })
        const saved = await api(`/assignments/${assignmentForm.id}`, { method: 'PATCH', body: JSON.stringify(payload) })
        assignmentForm.version = saved.version
        try {
          let copies = []
          if (additionalClassIds.length) {
            const created = await api('/assignments/bulk', { method: 'POST', body: JSON.stringify({
              class_ids: additionalClassIds,
              title: assignmentForm.title.trim(),
              description: assignmentForm.description,
              submitter_type: assignmentForm.submitter_type,
              kind: assignmentForm.kind,
              starts_at: ctx.iso(assignmentForm.starts_at),
              due_at: ctx.iso(assignmentForm.due_at),
              allow_late: assignmentForm.allow_late,
              publish: false,
              auto_review_enabled: assignmentForm.auto_review_enabled,
              auto_review_mode: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_mode : null,
              auto_review_criteria_text: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_criteria_text : '',
              auto_review_due_at: assignmentForm.auto_review_enabled ? ctx.iso(assignmentForm.auto_review_due_at) : null
            }) })
            copies = created.items
            await copyAssignmentFiles(copies)
          }
          await uploadPendingAssignmentFiles([saved, ...copies], saved.id)
          const copiesShouldPublish = ctx.selectedAssignment.value.status === 'PUBLISHED' || publishRequested
          if (copiesShouldPublish) await Promise.all(copies.map(item => api(`/assignments/${item.id}/publish`, { method: 'POST' })))
          if (publishRequested) await api(`/assignments/${assignmentForm.id}/publish`, { method: 'POST' })
          message.success(publishRequested ? '作业已更新并重新发布' : `作业已更新至 ${assignmentForm.class_ids.length} 个教学班`)
        } catch (error) {
          message.warning(`原作业已保存，但跨班处理未完成：${error.message}。请检查各班作业列表中的草稿和附件后再操作`)
        }
        ctx.modals.assignment = false
        await ctx.session.refreshClasses(saved.class_id)
      })
      return
    }
    const count = assignmentForm.class_ids.length
    const createPayload = {
      class_ids: [...assignmentForm.class_ids],
      title: assignmentForm.title.trim(),
      description: assignmentForm.description,
      submitter_type: assignmentForm.submitter_type,
      kind: assignmentForm.kind,
      starts_at: ctx.iso(assignmentForm.starts_at),
      due_at: ctx.iso(assignmentForm.due_at),
      allow_late: assignmentForm.allow_late,
      publish: false,
      auto_review_enabled: assignmentForm.auto_review_enabled,
      auto_review_mode: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_mode : null,
      auto_review_criteria_text: assignmentForm.auto_review_enabled ? assignmentForm.auto_review_criteria_text : '',
      auto_review_due_at: assignmentForm.auto_review_enabled ? ctx.iso(assignmentForm.auto_review_due_at) : null
    }
    try {
      const created = await api('/assignments/bulk', { method: 'POST', body: JSON.stringify(createPayload) })
      const failed = []
      for (const assignment of created.items) {
        for (const pending of pendingAssignmentFiles.value) {
          try {
            const body = new FormData(); body.append('file', pending.file)
            await api(`/assignments/${assignment.id}/files?material_type=${pending.materialType}`, { method: 'POST', body })
          } catch (error) { failed.push(`${assignment.title}：${pending.file.name}（${error.message}）`) }
        }
      }
      if (!failed.length && publishRequested) await Promise.all(created.items.map(item => api(`/assignments/${item.id}/publish`, { method: 'POST' })))
      pendingAssignmentFiles.value = []; ctx.modals.assignment = false; await ctx.session.refreshClasses(ctx.classId.value); await ctx.loadView()
      if (failed.length) message.warning(`草稿已保留，${failed.length} 个作业资料上传失败，可在作业详情中重试后发布`)
      else message.success(publishRequested ? `已向 ${count} 个教学班发布作业` : `已为 ${count} 个教学班保存草稿`)
    } catch (error) { message.error(error.message) }
  }

  async function uploadFile({ file, onSuccess, onError }) {
    try {
      const body = new FormData(); body.append('file', file); const saved = await api(`/assignments/${ctx.selectedAssignment.value.id}/files`, { method: 'POST', body })
      if (ctx.role.value === 'TEACHER') assignmentAttachments.value.push(saved)
      else draftFiles.value.push(saved)
      onSuccess(saved)
    } catch (e) { onError(e); message.error(e.message) }
  }

  async function uploadMaterialFile({ file, onSuccess, onError }) {
    try {
      const body = new FormData(); body.append('file', file)
      const saved = await api(`/assignments/${ctx.selectedAssignment.value.id}/files?material_type=${uploadMaterialType.value}`, { method: 'POST', body })
      assignmentAttachments.value.push(saved)
      onSuccess(saved)
    } catch (e) { onError(e); message.error(e.message) }
  }

  async function retypeMaterial(file, materialType) {
    try {
      const saved = await api(`/files/${file.id}`, { method: 'PATCH', body: JSON.stringify({ material_type: materialType }) })
      const index = assignmentAttachments.value.findIndex(item => item.id === file.id)
      if (index !== -1) assignmentAttachments.value[index] = saved
    } catch (e) { message.error(e.message) }
  }

  function deleteSelectedMaterials(files) {
    if (!files.length || deletingMaterials.value) return
    const assignment = ctx.selectedAssignment.value
    Modal.confirm({
      title: `确认删除 ${files.length} 个作业资料附件？`,
      content: '删除后无法恢复，学生提交记录不受影响。',
      okText: '确认删除', okType: 'danger', cancelText: '取消',
      onOk: async () => {
        if (deletingMaterials.value) return
        deletingMaterials.value = true
        try {
          const results = await Promise.allSettled(files.map(file => api(`/files/${file.id}`, { method: 'DELETE' })))
          await ctx.loadAssignmentDetail(assignment)
          const failed = results.filter(result => result.status === 'rejected')
          if (failed.length) message.error(`${files.length-failed.length} 个附件已删除，${failed.length} 个删除失败：${failed[0].reason.message}`)
          else message.success(`已删除 ${files.length} 个附件`)
        } catch (error) { message.error(error.message) }
        finally { deletingMaterials.value = false }
      }
    })
  }

  function deleteDraft(file) {
    const submitted = Boolean(file.submitted)
    Modal.confirm({
      title: submitted ? '从待更新附件中移除？' : '确认删除文件？',
      content: submitted ? '移除后需要点击“更新提交”生成新版本，历史提交记录不受影响。' : '删除后无法恢复。',
      okText: submitted ? '确认移除' : '确认删除',
      cancelText: '取消',
      onOk: () => ctx.action(async () => { await api(`/files/${file.id}`, { method: 'DELETE' }); await ctx.loadAssignmentDetail(ctx.selectedAssignment.value) }, submitted ? '已移除，请点击“更新提交”' : '文件已删除')
    })
  }

  async function publishAssignment() { await ctx.action(() => api(`/assignments/${ctx.selectedAssignment.value.id}/publish`, { method: 'POST' }), '作业已发布') }

  function retractAssignment() {
    Modal.confirm({ title: '确认撤回发布？', content: '撤回后学生将不能查看或提交，作业会回到草稿状态。', okText: '确认撤回', okType: 'danger', cancelText: '取消', onOk: () => ctx.action(() => api(`/assignments/${ctx.selectedAssignment.value.id}/retract`, { method: 'POST' }), '作业已撤回') })
  }

  function closeAssignment() {
    Modal.confirm({ title: '确认提前截止？', content: '截止后学生将不能继续上传或提交，已有提交和历史记录会保留。', okText: '确认截止', okType: 'danger', cancelText: '取消', onOk: () => ctx.action(() => api(`/assignments/${ctx.selectedAssignment.value.id}/close`, { method: 'POST' }), '作业已提前截止') })
  }

  function deleteAssignment() {
    Modal.confirm({ title: '确认永久删除作业？', content: '作业、附件、提交记录、关联互评和成绩都会从数据库中永久删除，且无法恢复。', okText: '永久删除', okType: 'danger', cancelText: '取消', onOk: () => ctx.action(async () => { await api(`/assignments/${ctx.selectedAssignment.value.id}`, { method: 'DELETE' }); ctx.selectedAssignment.value = null; await ctx.router.replace('/assignments') }, '作业已删除') })
  }

  async function downloadAssignmentSubmissions() {
    if (!ctx.selectedAssignment.value || exportingAssignment.value) return
    exportingAssignment.value = true
    try {
      await exportArchive(`/assignments/${ctx.selectedAssignment.value.id}/download.zip`)
      message.success('导出文件已生成')
    } catch (error) {
      message.error(error.message || '作业导出失败')
    } finally {
      exportingAssignment.value = false
    }
  }

  async function loadAssignmentsView(isCurrent, { background = false } = {}) {
      const [assignmentData, gradeData] = await Promise.all([
        api(`/assignments?class_id=${ctx.classId.value}`),
        ctx.role.value === 'STUDENT' ? api(`/grades?class_id=${ctx.classId.value}`) : Promise.resolve({ items: [] })
      ])
      if (!isCurrent()) return
      assignments.value = assignmentData.items
      if (ctx.role.value === 'STUDENT') ctx.grades.value = gradeData.items
    
  }

  return { assignments, assignmentForm, descriptionEditor, materialTypeOptions, uploadMaterialType, pendingAssignmentFiles, assignmentAttachments, reviewCriteriaFiles, draftFiles, deletingMaterials, exportingAssignment, studentPendingAssignments, studentUpcomingAssignments, studentCriteriaMaterials, gradingCriteriaFiles, openAssignmentCreate, openAssignmentEdit, setDescriptionLink, materialTypeOption, queueAssignmentAttachment, removePendingAssignmentAttachment, copyAssignmentFiles, uploadPendingAssignmentFiles, createAssignment, uploadFile, uploadMaterialFile, retypeMaterial, deleteSelectedMaterials, deleteDraft, publishAssignment, retractAssignment, closeAssignment, deleteAssignment, downloadAssignmentSubmissions, loadAssignmentsView }
}
