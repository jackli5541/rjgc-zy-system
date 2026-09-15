import { defineStore } from 'pinia'
import { api, setCsrfToken } from '../api'

export const useSessionStore = defineStore('session', {
  state: () => ({ user: null, context: null, classes: [], ready: false }),
  getters: {
    isTeacher: state => state.user?.role === 'TEACHER',
    classId: state => state.context?.current_class?.id || null,
    teamGate: state => Boolean(state.context?.team_gate_required)
  },
  actions: {
    async restore() {
      try {
        const data = await api('/auth/session')
        this.user = data.user
        setCsrfToken(data.csrf_token)
        await this.refreshClasses()
      } catch { this.user = null }
      finally { this.ready = true }
    },
    async login(payload) {
      const data = await api('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
      this.user = data.user
      setCsrfToken(data.csrf_token)
      await this.refreshClasses()
    },
    async refreshClasses(preferredId) {
      const data = await api('/classes')
      this.classes = data.items
      const requested = preferredId || this.context?.current_class?.id
      const id = this.classes.some(item => item.id === requested) ? requested : this.classes[0]?.id
      this.context = await api(`/classes/current/context${id ? `?class_id=${id}` : ''}`)
    },
    async refreshContext() { if (this.user) await this.refreshClasses(this.classId) },
    async logout() {
      await api('/auth/logout', { method: 'POST' })
      this.user = null; this.context = null; this.classes = []; setCsrfToken('')
    }
  }
})
