import { defineStore } from 'pinia'
import { api, setCsrfToken } from '../api'

const teacherClassKey = userId => `coursework:last-teacher-class:${userId}`

export const useSessionStore = defineStore('session', {
  state: () => ({ user: null, context: null, classes: [], menuPermissions: null, ready: false }),
  getters: {
    isTeacher: state => state.user?.role === 'TEACHER',
    classId: state => state.context?.current_class?.id || null,
    teamGate: state => Boolean(state.context?.team_gate_required),
    isMenuEnabled: state => key => state.menuPermissions === null || state.menuPermissions.includes(key),
    landingPath: state => {
      if (state.context?.team_gate_required) return '/teams'
      const order = state.user?.role === 'TEACHER'
        ? ['overview', 'classes', 'teams', 'assignments', 'capstone', 'materials', 'grades', 'system']
        : ['overview', 'teams', 'assignments', 'reviews', 'capstone', 'grades', 'materials']
      const first = order.find(key => state.menuPermissions === null || state.menuPermissions.includes(key))
      return first ? `/${first}` : state.user?.role === 'TEACHER' ? '/menu-permissions' : '/login'
    }
  },
  actions: {
    clear() {
      this.user = null
      this.context = null
      this.classes = []
      this.menuPermissions = null
      this.ready = true
      setCsrfToken('')
    },
    async restore() {
      try {
        const data = await api('/auth/session')
        this.user = data.user
        setCsrfToken(data.csrf_token)
        await Promise.all([this.refreshClasses(), this.refreshMenuPermissions()])
      } catch { this.clear() }
      finally { this.ready = true }
    },
    async login(payload) {
      const data = await api('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
      this.user = data.user
      setCsrfToken(data.csrf_token)
      await Promise.all([this.refreshClasses(), this.refreshMenuPermissions()])
    },
    async refreshMenuPermissions() {
      const data = await api('/menu-permissions')
      this.menuPermissions = data.enabled
      return data
    },
    async refreshClasses(preferredId) {
      const data = await api('/classes')
      this.classes = data.items
      const remembered = this.user?.role === 'TEACHER' ? localStorage.getItem(teacherClassKey(this.user.id)) : null
      const requested = preferredId || this.context?.current_class?.id || remembered
      const id = this.classes.some(item => item.id === requested) ? requested : this.classes[0]?.id
      this.context = await api(`/classes/current/context${id ? `?class_id=${id}` : ''}`)
      if (this.user?.role === 'TEACHER' && this.context?.current_class?.id) localStorage.setItem(teacherClassKey(this.user.id), this.context.current_class.id)
    },
    async refreshContext() { if (this.user) await this.refreshClasses(this.classId) },
    async logout() {
      try { await api('/auth/logout', { method: 'POST' }) } finally { this.clear() }
    }
  }
})
