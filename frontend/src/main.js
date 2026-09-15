import { createApp } from 'vue'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import './style.css'
import App from './App.vue'
import { createPinia } from 'pinia'
import router from './router'

createApp(App).use(createPinia()).use(router).use(Antd).mount('#app')
