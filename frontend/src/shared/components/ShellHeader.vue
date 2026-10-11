<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BellOutlined, CalendarOutlined, CodeOutlined, DownOutlined, LogoutOutlined, MenuOutlined, UserOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'

const { session, role, classId, menu, navView, notifications, noticesOpen, attendanceOpen, modals, changeClass, logout, navigate } = useShellContext()
const moreOpen = ref(false)
const topNav = ref(null)
const underline = ref({ left: 0, width: 0 })
let navObserver
function updateUnderline() {
  const nav = topNav.value
  const active = nav?.querySelector('button.active')
  if (!active || !nav.clientWidth) { underline.value = { left: 0, width: 0 }; return }
  const navRect = nav.getBoundingClientRect()
  const buttonRect = active.getBoundingClientRect()
  const inset = parseFloat(getComputedStyle(active).paddingLeft) || 18
  underline.value = { left: buttonRect.left - navRect.left + nav.scrollLeft + inset, width: Math.max(0, buttonRect.width - inset * 2) }
}
watch([navView, menu], updateUnderline, { flush: 'post' })
onMounted(() => {
  navObserver = new ResizeObserver(updateUnderline)
  navObserver.observe(topNav.value)
  updateUnderline()
})
onBeforeUnmount(() => navObserver?.disconnect())
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
        <a-badge :count="notifications.filter(x=>!x.read).length" size="small"><a-button class="header-notification" type="text" shape="circle" aria-label="查看通知" @click="noticesOpen=true"><BellOutlined /></a-button></a-badge>
        <a-button v-if="role==='STUDENT'" class="student-attendance-trigger" type="primary" @click="attendanceOpen=true"><CalendarOutlined/> 签到</a-button>
        <div class="header-account">
          <a-dropdown :trigger="['click']"><button type="button" class="user-chip" aria-label="打开个人菜单"><a-avatar class="header-user-avatar">{{ session.user.name.slice(0,1) }}</a-avatar><div class="user-meta"><strong>{{ session.user.name }}</strong><span>{{ role==='TEACHER'?'教师':'学生' }}</span></div><DownOutlined class="user-menu-arrow"/></button><template #overlay><a-menu><a-menu-item @click="modals.password=true"><UserOutlined /> 修改密码</a-menu-item><a-menu-item @click="logout"><LogoutOutlined /> 退出登录</a-menu-item></a-menu></template></a-dropdown>
        </div>
      </div>
    </div>
    <nav ref="topNav" class="top-nav" aria-label="主导航"><button v-for="item in menu" :key="item[0]" :class="{active:navView===item[0]}" @click="navigate('/'+item[0])"><component :is="item[1]" />{{ item[2] }}</button><span class="nav-underline" aria-hidden="true" :style="{width:`${underline.width}px`,transform:`translateX(${underline.left}px)`}" /></nav>
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

<style scoped>
.header-right { gap: 12px }
.header-notification.ant-btn { width: 36px; height: 36px; background: #f0f3f5; color: #647588 }
.header-notification.ant-btn:hover { background: #e7edf2; color: #176b78 }
.student-attendance-trigger.ant-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 36px; min-width: 76px; padding: 0 12px; border: 1px solid #176b78; border-radius: 8px; background: #176b78; color: #fff; font-size: 13px; font-weight: 600; box-shadow: none }
.student-attendance-trigger.ant-btn:hover, .student-attendance-trigger.ant-btn:focus-visible { border-color: #125864; background: #125864; color: #fff }
.header-account { margin-left: 4px; padding-left: 16px; border-left: 1px solid #dfe7ed }
.user-chip { min-height: 42px; padding: 4px 7px; border: 0; border-radius: 8px; background: transparent; color: #25384b; font: inherit; line-height: normal; text-align: left; transition: background .16s ease }
.user-chip:hover { background: #eef3f7 }
.user-chip:focus-visible { outline: 2px solid #176b78; outline-offset: 3px }
.header-user-avatar { flex: none; background: #e7f3f5; color: #176b78; font-weight: 600; border: 1px solid #cfe2e5 }
.user-meta { min-width: 0 }
.user-meta strong { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 600; line-height: 1.4 }
.user-meta span { margin-top: 2px; color: #8a98a6; font-size: 11px; line-height: 1.3 }
.user-menu-arrow { margin-left: 5px; color: #8a98a6; font-size: 10px }
@media (max-width: 760px) {
  .header-right { gap: 8px }
  .header-account { margin-left: 0; padding-left: 8px }
  .user-chip { gap: 6px; min-height: 44px; padding-inline: 4px }
  .header-notification.ant-btn { width: 40px; height: 40px }
  .student-attendance-trigger.ant-btn { min-width: 68px; height: 44px; padding-inline: 10px }
  .user-menu-arrow { margin-left: 0 }
}
@media (prefers-reduced-motion: reduce) {
  .user-chip { transition: none }
}
</style>
