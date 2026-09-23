<script setup>
import { BellOutlined, CodeOutlined, LogoutOutlined, UserOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'

const { session, role, classId, menu, navView, notifications, noticesOpen, modals, changeClass, logout, navigate } = useShellContext()
</script>

<template>
  <a-layout-header class="app-header">
    <div class="header-toolbar">
      <div class="header-left">
        <div class="header-brand"><div class="brand-mark"><CodeOutlined /></div><strong>软件工程</strong></div>
        <a-select v-if="session.classes.length" class="class-switch" :value="classId" :options="session.classes.map(x => ({value:x.id,label:`${x.semester} · ${x.name}`}))" @change="changeClass" />
      </div>
      <div class="header-right">
        <a-badge :count="notifications.filter(x=>!x.read).length" size="small"><a-button type="text" shape="circle" @click="noticesOpen=true"><BellOutlined /></a-button></a-badge>
        <a-dropdown><div class="user-chip"><a-avatar :style="{background:role==='TEACHER'?'#7352bd':'#1769aa'}">{{ session.user.name.slice(0,1) }}</a-avatar><div class="user-meta"><strong>{{ session.user.name }}</strong><span>{{ role==='TEACHER'?'教师':'学生' }}</span></div></div><template #overlay><a-menu><a-menu-item @click="modals.password=true"><UserOutlined /> 修改密码</a-menu-item><a-menu-item @click="logout"><LogoutOutlined /> 退出登录</a-menu-item></a-menu></template></a-dropdown>
      </div>
    </div>
    <nav class="top-nav" aria-label="主导航"><button v-for="item in menu" :key="item[0]" :class="{active:navView===item[0]}" @click="navigate('/'+item[0])"><component :is="item[1]" />{{ item[2] }}</button></nav>
  </a-layout-header>
</template>
