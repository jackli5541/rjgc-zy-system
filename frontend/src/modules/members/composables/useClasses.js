import { api } from '../../../api'
import { Modal, message } from 'ant-design-vue'
import { computed, reactive } from 'vue'

export function useClasses(ctx) {
  const classForm = reactive({ id: '', version: 1, semester: '', name: '', team_deadline: '', topic_public: false })

  const activeClasses = computed(() => ctx.session.classes.filter(item => item.status === 'ACTIVE'))

  const classOptions = computed(() => activeClasses.value.map(item => ({ value: item.id, label: `${item.semester} · ${item.name}` })))

  async function changeClass(id) {
    await ctx.session.refreshClasses(id)
    const target = ctx.session.landingPath
    if (ctx.route.path === target) await ctx.loadView()
    else await ctx.router.replace(target)
    await ctx.loadNotifications()
  }

  async function manageClass(item) { await ctx.session.refreshClasses(item.id); await ctx.router.push({ name: 'class-detail', params: { id: item.id } }) }

  async function closeClassDetail() { await ctx.router.replace('/classes') }

  function openClassCreate() {
    Object.assign(classForm, { id: '', version: 1, semester: '', name: '', team_deadline: '', topic_public: false }); ctx.modals.class = true
  }

  function openClassEdit(item) {
    Object.assign(classForm, { id: item.id, version: item.version, semester: item.semester, name: item.name, team_deadline: ctx.localDateTime(item.team_deadline), topic_public: item.topic_public }); ctx.modals.class = true
  }

  async function saveClass() {
    if (!classForm.semester.trim() || !classForm.name.trim()) return message.warning('请填写学期和班级名称')
    const payload = { semester: classForm.semester, name: classForm.name, team_deadline: ctx.iso(classForm.team_deadline), topic_public: classForm.topic_public }
    const editing = Boolean(classForm.id)
    await ctx.action(async () => {
      const saved = editing
        ? await api(`/classes/${classForm.id}`, { method: 'PATCH', body: JSON.stringify({ ...payload, version: classForm.version }) })
        : await api('/classes', { method: 'POST', body: JSON.stringify(payload) })
      ctx.modals.class = false; await ctx.session.refreshClasses(saved.id)
    }, editing ? '教学班资料已更新' : '教学班已创建')
  }

  async function toggleClassStatus(item) {
    const status = item.status === 'ACTIVE' ? 'ARCHIVED' : 'ACTIVE'
    await ctx.action(async () => {
      await api(`/classes/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status, version: item.version }) })
      await ctx.session.refreshClasses(ctx.classId.value)
    }, status === 'ARCHIVED' ? '教学班已归档' : '教学班已恢复')
  }

  function deleteClass(item) {
    Modal.confirm({
      title: `删除教学班“${item.name}”？`, content: '仅无名单、成员、小组和作业记录的空班可以删除。', okText: '确认删除', okType: 'danger',
      onOk: () => ctx.action(async () => {
        await api(`/classes/${item.id}`, { method: 'DELETE' })
        const fallback = item.id === ctx.classId.value ? ctx.session.classes.find(course => course.id !== item.id)?.id : ctx.classId.value
        await ctx.session.refreshClasses(fallback)
      }, '教学班已删除')
    })
  }

  function defaultClassSelection() {
    if (activeClasses.value.some(item => item.id === ctx.classId.value)) return [ctx.classId.value]
    return activeClasses.value[0] ? [activeClasses.value[0].id] : []
  }

  return { classForm, activeClasses, classOptions, changeClass, manageClass, closeClassDetail, openClassCreate, openClassEdit, saveClass, toggleClassStatus, deleteClass, defaultClassSelection }
}
