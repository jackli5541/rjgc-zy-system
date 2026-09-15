<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { CodeOutlined } from '@ant-design/icons-vue'
import { useSessionStore } from '../stores/session'

const form = reactive({ account: '', password: '', role: 'student' })
const loading = ref(false)
const session = useSessionStore()
const router = useRouter()

async function submit() {
  if (!form.account || !form.password) return message.warning('请输入账号和密码')
  loading.value = true
  try {
    await session.login(form)
    await router.replace(session.teamGate ? '/teams' : '/overview')
  } catch (error) { message.error(error.message) }
  finally { loading.value = false }
}
</script>

<template>
  <main class="login-page">
    <section class="login-visual">
      <div class="visual-inner"><div class="brand-mark large"><CodeOutlined /></div><div class="visual-kicker">软件工程课程空间</div><h1>让作业流转<br><span>清晰、可追踪。</span></h1><p>从组队、选题到提交与互评，课程工作在一个空间内完成。</p></div>
    </section>
    <section class="login-panel">
      <div class="login-box">
        <div class="brand-row"><div class="brand-mark"><CodeOutlined /></div><strong>软件工程作业系统</strong></div>
        <div class="login-heading"><h2>登录课程空间</h2><p>使用教师工号或学生学号登录</p></div>
        <a-form layout="vertical">
          <a-form-item label="身份"><a-segmented v-model:value="form.role" :options="[{label:'学生',value:'student'},{label:'教师',value:'teacher'}]" block /></a-form-item>
          <a-form-item label="账号" required><a-input v-model:value="form.account" size="large" autocomplete="username" placeholder="学号 / 工号" /></a-form-item>
          <a-form-item label="密码" required><a-input-password v-model:value="form.password" size="large" autocomplete="current-password" placeholder="请输入密码" @pressEnter="submit" /></a-form-item>
          <a-button type="primary" html-type="button" size="large" block :loading="loading" @click="submit">进入课程空间</a-button>
        </a-form>
      </div>
    </section>
  </main>
</template>
