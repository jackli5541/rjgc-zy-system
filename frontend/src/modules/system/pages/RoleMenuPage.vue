<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { ApartmentOutlined, BookOutlined, DashboardOutlined, FileTextOutlined, FolderOpenOutlined, FormOutlined, SettingOutlined, TeamOutlined, TrophyOutlined } from '@ant-design/icons-vue'
import { api } from '../../../api'
import { useSessionStore } from '../../../stores/session'

const session = useSessionStore()
const loading = ref(true)
const saving = ref(false)
const catalog = ref([])
const roles = ref({ TEACHER: [], STUDENT: [] })
const savedSnapshot = ref('')
const icons = {
  overview: DashboardOutlined,
  classes: BookOutlined,
  teams: TeamOutlined,
  assignments: FileTextOutlined,
  reviews: FormOutlined,
  capstone: ApartmentOutlined,
  materials: FolderOpenOutlined,
  grades: TrophyOutlined,
  system: SettingOutlined
}

const snapshot = computed(() => JSON.stringify(roles.value))
const dirty = computed(() => savedSnapshot.value && snapshot.value !== savedSnapshot.value)
const roleCounts = computed(() => ({
  TEACHER: roles.value.TEACHER.length,
  STUDENT: roles.value.STUDENT.length
}))

function applyPayload(data) {
  catalog.value = data.catalog || []
  roles.value = {
    TEACHER: [...(data.roles?.TEACHER || [])],
    STUDENT: [...(data.roles?.STUDENT || [])]
  }
  savedSnapshot.value = JSON.stringify(roles.value)
  session.menuPermissions = data.enabled || roles.value.TEACHER
}

function applies(item, role) { return item.roles.includes(role) }
function enabled(item, role) { return roles.value[role].includes(item.key) }
function setEnabled(item, role, checked) {
  const next = new Set(roles.value[role])
  if (checked) next.add(item.key); else next.delete(item.key)
  roles.value = { ...roles.value, [role]: catalog.value.filter(entry => next.has(entry.key)).map(entry => entry.key) }
}

function restoreDefaults() {
  roles.value = {
    TEACHER: catalog.value.filter(item => applies(item, 'TEACHER')).map(item => item.key),
    STUDENT: catalog.value.filter(item => applies(item, 'STUDENT')).map(item => item.key)
  }
}

async function load() {
  loading.value = true
  try { applyPayload(await api('/menu-permissions')) }
  catch (error) { message.error(error.message) }
  finally { loading.value = false }
}

async function save() {
  if (!roles.value.TEACHER.length || !roles.value.STUDENT.length) return message.warning('每个角色至少保留一个模块')
  saving.value = true
  try {
    applyPayload(await api('/menu-permissions', { method: 'PUT', body: JSON.stringify({ roles: roles.value }) }))
    message.success('角色菜单配置已保存')
  } catch (error) { message.error(error.message) }
  finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <div class="page-title role-menu-page-title">
    <div><div class="eyebrow">访问配置</div><h1>角色菜单配置</h1><p>按角色控制一级功能模块的显示范围。</p></div>
    <a-space><a-button :disabled="loading" @click="restoreDefaults">恢复默认</a-button><a-button type="primary" :loading="saving" :disabled="!dirty" @click="save">保存配置</a-button></a-space>
  </div>
  <a-card class="panel-card role-menu-panel" :bordered="false" :loading="loading">
    <div class="role-menu-summary">
      <div><span>教师可见</span><strong>{{roleCounts.TEACHER}}</strong><small>个模块</small></div>
      <div><span>学生可见</span><strong>{{roleCounts.STUDENT}}</strong><small>个模块</small></div>
      <p>“角色菜单配置”固定对教师可见，不参与开关设置。</p>
    </div>
    <a-table :data-source="catalog" row-key="key" :pagination="false" :scroll="{x:720}">
      <a-table-column title="功能模块" :width="300">
        <template #default="{record}"><div class="role-menu-module"><span><component :is="icons[record.key]" /></span><div><strong>{{record.labels.TEACHER||record.labels.STUDENT}}</strong><small>{{record.key}}</small></div></div></template>
      </a-table-column>
      <a-table-column title="教师（TEACHER）" :width="210" align="center">
        <template #default="{record}"><div v-if="applies(record,'TEACHER')" class="role-menu-switch"><a-switch :checked="enabled(record,'TEACHER')" @change="checked=>setEnabled(record,'TEACHER',checked)"/><span>{{enabled(record,'TEACHER')?'显示':'隐藏'}}</span></div><span v-else class="role-menu-na">不适用</span></template>
      </a-table-column>
      <a-table-column title="学生（STUDENT）" :width="210" align="center">
        <template #default="{record}"><div v-if="applies(record,'STUDENT')" class="role-menu-switch"><a-switch :checked="enabled(record,'STUDENT')" @change="checked=>setEnabled(record,'STUDENT',checked)"/><span>{{enabled(record,'STUDENT')?'显示':'隐藏'}}</span></div><span v-else class="role-menu-na">不适用</span></template>
      </a-table-column>
    </a-table>
  </a-card>
</template>
