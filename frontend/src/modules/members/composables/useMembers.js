import { api } from '../../../api'
import { Modal, message } from 'ant-design-vue'
import { computed, reactive, ref } from 'vue'

export function useMembers(ctx) {
  const members = ref([])

  const memberDetail = ref(null)

  const memberQuery = ref('')

  const memberSaving = ref(false)

  const memberForm = reactive({ id: '', student_no: '', name: '' })

  const filteredMembers = computed(() => {
    const query = memberQuery.value.trim().toLocaleLowerCase()
    return members.value.filter(item => {
      const matchesQuery = !query || `${item.student_no} ${item.name} ${item.team || ''}`.toLocaleLowerCase().includes(query)
      return matchesQuery
    })
  })

  const ungroupedMembers = computed(() => members.value.filter(item => !item.team))

  function openMemberCreate() { Object.assign(memberForm, { id: '', student_no: '', name: '' }); ctx.modals.member = true }

  function openMemberEdit(item) { Object.assign(memberForm, { id: item.id, student_no: item.student_no, name: item.name }); ctx.modals.member = true }

  async function openMemberDetail(item) {
    memberDetail.value = item
  }

  async function saveMember() {
    if (!memberForm.student_no.trim() || !memberForm.name.trim()) return message.warning('请填写学号和姓名')
    memberSaving.value = true
    try {
      if (memberForm.id) await api(`/classes/${ctx.classId.value}/members/${memberForm.id}`, { method: 'PATCH', body: JSON.stringify({ name: memberForm.name }) })
      else await api(`/classes/${ctx.classId.value}/members`, { method: 'POST', body: JSON.stringify({ student_no: memberForm.student_no, name: memberForm.name }) })
      ctx.modals.member = false; message.success(memberForm.id ? '成员信息已更新' : '成员已添加'); await ctx.loadView()
    } catch (e) { message.error(e.message) } finally { memberSaving.value = false }
  }

  function resetMemberPassword(item) { Modal.confirm({ title: `重置 ${item.name} 的密码？`, content: '密码将重置为当前学号。', okText: '确认重置', onOk: () => ctx.action(() => api(`/classes/${ctx.classId.value}/members/${item.id}/reset-password`, { method: 'POST' }), '密码已重置') }) }

  function removeClassMember(item) { Modal.confirm({ title: `将 ${item.name} 移出教学班？`, content: item.team ? `该成员也会退出小组「${item.team}」。` : '历史提交和成绩将继续保留。', okText: '确认移出', okType: 'danger', onOk: () => ctx.action(async () => { await api(`/classes/${ctx.classId.value}/members/${item.id}`, { method: 'DELETE' }); memberDetail.value = null }, '成员已移出') }) }

  async function loadClassDetailView(isCurrent, { background = false } = {}) {
      if (ctx.classId.value !== ctx.detailId.value) await ctx.session.refreshClasses(ctx.detailId.value)
      if (!isCurrent()) return
      if (ctx.classId.value !== ctx.detailId.value) { message.error('教学班不存在或无权查看'); await ctx.router.replace('/classes'); return }
      const memberData = await api(`/classes/${ctx.classId.value}/members`)
      if (!isCurrent()) return
      members.value = memberData.items
    
  }

  return { members, memberDetail, memberQuery, memberSaving, memberForm, filteredMembers, ungroupedMembers, openMemberCreate, openMemberEdit, openMemberDetail, saveMember, resetMemberPassword, removeClassMember, loadClassDetailView }
}
