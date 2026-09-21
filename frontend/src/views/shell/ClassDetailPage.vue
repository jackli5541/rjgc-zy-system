<script setup>
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { ArrowLeftOutlined, DownloadOutlined, EyeOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { exportArchive } from '../../api'
import { useShellContext } from '../../shellContext'
const { session, classId, memberQuery, filteredMembers, modals, closeClassDetail, openMemberCreate, openMemberDetail, statusLabel } = useShellContext()
const exporting = ref(false)
async function exportClass() {
  exporting.value = true
  try { await exportArchive(`/classes/${classId.value}/portfolio.zip`) }
  catch (e) { message.error(e.message) }
  finally { exporting.value = false }
}
</script>

<template>
  <div class="page-title detail-title"><div><div class="eyebrow">教学班详情</div><h1>{{session.context?.current_class?.name}}</h1><p>{{session.context?.current_class?.semester}}</p></div><a-button @click="closeClassDetail"><ArrowLeftOutlined/> 返回教学班列表</a-button></div>
  <a-card class="panel-card" :bordered="false">
    <div class="card-toolbar class-portfolio-toolbar"><div><strong>{{session.context?.current_class?.name}}成员</strong><span class="class-member-caption">{{session.context?.current_class?.semester}}</span></div><a-space wrap>
      <a-input-search v-model:value="memberQuery" allow-clear placeholder="搜索学号、姓名或小组" style="width:240px;max-width:100%"/>
      <a-button :loading="exporting" @click="exportClass"><DownloadOutlined/> 导出班级 ZIP</a-button>
      <a-button @click="modals.import=true" :disabled="session.context?.current_class?.status!=='ACTIVE'"><UploadOutlined/> 导入名单</a-button>
      <a-button type="primary" :disabled="session.context?.current_class?.status!=='ACTIVE'" @click="openMemberCreate"><PlusOutlined/> 添加成员</a-button>
    </a-space></div>
    <a-table :data-source="filteredMembers" row-key="id" :pagination="{pageSize:10}" :scroll="{x:700}">
      <a-table-column title="学号" data-index="student_no"/><a-table-column title="姓名" data-index="name"/>
      <a-table-column title="小组"><template #default="{record}">{{record.team||'未入组'}}</template></a-table-column>
      <a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag></template></a-table-column>
      <a-table-column title="操作" :width="80"><template #default="{record}"><a-tooltip title="查看学生档案"><a-button type="text" shape="circle" aria-label="查看学生档案" @click="openMemberDetail(record)"><EyeOutlined/></a-button></a-tooltip></template></a-table-column>
    </a-table>
  </a-card>
</template>

<style scoped>
.class-portfolio-toolbar{flex-wrap:wrap;gap:14px}
</style>
