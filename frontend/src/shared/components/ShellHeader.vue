<script setup>
import { computed, ref, watch } from 'vue'
import { BellOutlined, CodeOutlined, LogoutOutlined, MenuOutlined, UserOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'

const { session, role, classId, menu, navView, notifications, noticesOpen, attendanceOpen, modals, changeClass, logout, navigate } = useShellContext()
const moreOpen = ref(false)
const priority = computed(() => role.value === 'TEACHER'
  ? ['overview', 'classes', 'assignments', 'attendance']
  : ['overview', 'assignments', 'reviews', 'teams'])
const primaryMenu = computed(() => priority.value.map(key => menu.value.find(item => item[0] === key)).filter(Boolean))
const moreMenu = computed(() => menu.value.filter(item => !primaryMenu.value.includes(item)))
watch(navView, () => { moreOpen.value = false })
function openPage(key) {
  moreOpen.value = false
  navigate('/' + key)
}
</script>

<template>
  <a-layout-header class="app-header" :class="{'student-header':role==='STUDENT'}">
    <div class="header-toolbar">
      <div class="header-left">
        <div class="header-brand"><div class="brand-mark"><CodeOutlined /></div><strong>软件工程</strong></div>
        <a-select v-if="session.classes.length" class="class-switch" :value="classId" :options="session.classes.map(x => ({value:x.id,label:`${x.semester} · ${x.name}`}))" @change="changeClass" />
      </div>
      <div class="header-right">
        <a-badge :count="notifications.filter(x=>!x.read).length" size="small"><a-button type="text" shape="circle" @click="noticesOpen=true"><BellOutlined /></a-button></a-badge>
        <a-button v-if="role==='STUDENT'" class="student-attendance-trigger" type="primary" @click="attendanceOpen=true">签到</a-button>
        <a-dropdown><div class="user-chip"><a-avatar :style="{background:role==='TEACHER'?'#7352bd':'#1769aa'}">{{ session.user.name.slice(0,1) }}</a-avatar><div class="user-meta"><strong>{{ session.user.name }}</strong><span>{{ role==='TEACHER'?'教师':'学生' }}</span></div></div><template #overlay><a-menu><a-menu-item @click="modals.password=true"><UserOutlined /> 修改密码</a-menu-item><a-menu-item @click="logout"><LogoutOutlined /> 退出登录</a-menu-item></a-menu></template></a-dropdown>
      </div>
    </div>
    <nav class="top-nav" aria-label="主导航"><button v-for="item in menu" :key="item[0]" :class="{active:navView===item[0]}" @click="navigate('/'+item[0])"><component :is="item[1]" />{{ item[2] }}</button></nav>
  </a-layout-header>
  <nav class="mobile-nav" aria-label="手机主导航">
    <button v-for="item in primaryMenu" :key="item[0]" type="button" :class="{active:navView===item[0]}" :aria-current="navView===item[0]?'page':undefined" @click="openPage(item[0])"><component :is="item[1]" /><span>{{ item[2] }}</span></button>
    <button v-if="moreMenu.length" type="button" :class="{active:moreMenu.some(item=>item[0]===navView)}" :aria-expanded="moreOpen" aria-controls="mobile-more-menu" @click="moreOpen=true"><MenuOutlined /><span>更多</span></button>
  </nav>
  <a-drawer v-model:open="moreOpen" title="更多功能" placement="bottom" class="mobile-more-drawer" :height="'min(70dvh, 480px)'">
    <nav id="mobile-more-menu" class="mobile-more-list" aria-label="其他页面">
      <button v-for="item in moreMenu" :key="item[0]" type="button" :class="{active:navView===item[0]}" :aria-current="navView===item[0]?'page':undefined" @click="openPage(item[0])"><component :is="item[1]" /><span>{{ item[2] }}</span></button>
    </nav>
  </a-drawer>
</template>
