import { api } from '../../../api'
import { message } from 'ant-design-vue'
import { ref } from 'vue'

export function useNotifications(ctx) {
  const notifications = ref([])

  const noticesOpen = ref(false)
  const notificationsHasMore = ref(false)
  const notificationsLoading = ref(false)
  let historyOffset = 0
  let refreshVersion = 0
  let loadingPromise

  async function loadNotifications() {
    if (loadingPromise) return loadingPromise
    const version = ++refreshVersion
    if (!ctx.classId.value) { notifications.value = []; notificationsHasMore.value = false; return }
    loadingPromise = (async () => { try {
      const noticeData = await api('/notifications')
      if (version !== refreshVersion) return
      notifications.value = noticeData.items
      notificationsHasMore.value = noticeData.has_more
      historyOffset = noticeData.next_offset
    } catch (_) { /* Notification refresh must not block page navigation or completed actions. */ }
    finally { loadingPromise = undefined }
    })()
    return loadingPromise
  }

  async function loadNotificationHistory() {
    if (notificationsLoading.value || !notificationsHasMore.value) return
    const version = refreshVersion
    notificationsLoading.value = true
    try {
      const data = await api(`/notifications?history=true&offset=${historyOffset}`)
      if (version !== refreshVersion) return
      const existing = new Set(notifications.value.map(item => item.id))
      notifications.value.push(...data.items.filter(item => !existing.has(item.id)))
      notificationsHasMore.value = data.has_more
      historyOffset = data.next_offset
    } catch (error) { message.error(error.message) }
    finally { notificationsLoading.value = false }
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

  return { notifications, noticesOpen, notificationsHasMore, notificationsLoading, loadNotifications, loadNotificationHistory, readAll, openNotification }
}
