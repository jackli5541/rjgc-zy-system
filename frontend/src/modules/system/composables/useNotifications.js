import { api } from '../../../api'
import { message } from 'ant-design-vue'
import { ref } from 'vue'

export function useNotifications(ctx) {
  const notifications = ref([])

  const noticesOpen = ref(false)

  async function loadNotifications() {
    if (!ctx.classId.value) { notifications.value = []; return }
    try {
      const noticeData = await api('/notifications')
      notifications.value = noticeData.items
    } catch (_) { /* Notification refresh must not block page navigation or completed actions. */ }
  }

  async function readAll() {
    try {
      await api('/notifications/read', { method: 'POST' })
      notifications.value = notifications.value.map(item => ({ ...item, read: true }))
      await loadNotifications()
      message.success('已全部标为已读')
      noticesOpen.value = false
    } catch (error) { message.error(error.message) }
  }

  async function openNotification(item) {
    if (!item.link) return
    noticesOpen.value = false
    await ctx.router.push(item.link)
  }

  return { notifications, noticesOpen, loadNotifications, readAll, openNotification }
}
