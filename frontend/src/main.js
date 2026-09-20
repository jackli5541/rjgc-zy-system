import { createApp } from 'vue'
import 'ant-design-vue/dist/reset.css'
import './style.css'
import App from './App.vue'
import { createPinia } from 'pinia'
import router from './router'
import { useSessionStore } from './stores/session'

const pinia = createPinia()
window.addEventListener('auth-expired', () => {
  useSessionStore(pinia).clear()
  if (router.currentRoute.value.name !== 'login') router.replace('/login')
})

createApp(App).use(pinia).use(router).mount('#app')
