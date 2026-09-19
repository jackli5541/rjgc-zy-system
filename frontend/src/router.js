import { createRouter, createWebHistory } from 'vue-router'
import { useSessionStore } from './stores/session'
import LoginView from './views/LoginView.vue'
import ShellView from './views/ShellView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/assignments/:id', name: 'assignment-detail', component: ShellView },
    { path: '/classes/:id', name: 'class-detail', component: ShellView },
    { path: '/reviews/:id', redirect: '/reviews' },
    { path: '/grades/:id', name: 'grade-detail', component: ShellView },
    { path: '/:view(overview|classes|teams|assignments|reviews|grades|system)?', name: 'app', component: ShellView }
  ]
})

router.beforeEach(async to => {
  const session = useSessionStore()
  if (!session.ready) await session.restore()
  if (!session.user && to.name !== 'login') return '/login'
  if (session.user && to.name === 'login') return session.teamGate ? '/teams' : '/overview'
  if (session.user?.role === 'STUDENT' && session.teamGate && to.params.view !== 'teams') return '/teams'
  return true
})

export default router
