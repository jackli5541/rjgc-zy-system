<script setup>
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { DeleteOutlined, DownloadOutlined, EditOutlined, EyeOutlined, InboxOutlined, PlusOutlined, RedoOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { downloadArchive } from '../../api'
import { useShellContext } from '../../shellContext'
const { session, classId, memberQuery, filteredMembers, modals, openClassCreate, manageClass, openClassEdit, toggleClassStatus, deleteClass, openMemberCreate, openMemberDetail, statusLabel } = useShellContext()
const exporting = ref(false)
async function exportClass() {
  exporting.value = true
  try { await downloadArchive(`/classes/${classId.value}/portfolio.zip`) }
  catch (e) { message.error(e.message) }
  finally { exporting.value = false }
}
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">课程管理</div><h1>教学班</h1><p>管理教学班资料、状态和正式成员名单。</p></div><a-button type="primary" @click="openClassCreate"><PlusOutlined /> 创建教学班</a-button></div>
  <a-card class="panel-card class-list-panel" :bordered="false"><a-empty v-if="!session.classes.length" description="暂无教学班"/><a-table v-else :data-source="session.classes" row-key="id" :pagination="false" :scroll="{x:760}"><a-table-column title="学期" data-index="semester"/><a-table-column title="班级名称" data-index="name"/><a-table-column title="成员" data-index="member_count" :width="90"/><a-table-column title="作业" data-index="assignment_count" :width="90"/><a-table-column title="状态" :width="100"><template #default="{record}"><a-tag :color="record.status==='ACTIVE'?'green':'default'">{{record.status==='ACTIVE'?'进行中':'已归档'}}</a-tag></template></a-table-column><a-table-column title="操作" :width="270" fixed="right"><template #default="{record}"><a-space><a-tooltip title="管理教学班"><a-button type="text" shape="circle" @click="manageClass(record)"><EyeOutlined/></a-button></a-tooltip><a-tooltip title="编辑教学班"><a-button type="text" shape="circle" :disabled="record.status!=='ACTIVE'" @click="openClassEdit(record)"><EditOutlined/></a-button></a-tooltip><a-tooltip :title="record.status==='ACTIVE'?'归档教学班':'恢复教学班'"><a-button type="text" shape="circle" @click="toggleClassStatus(record)"><InboxOutlined v-if="record.status==='ACTIVE'"/><RedoOutlined v-else/></a-button></a-tooltip><a-tooltip :title="record.deletable?'删除空班':'已有历史数据，只能归档'"><span><a-button danger type="text" shape="circle" :disabled="!record.deletable" @click="deleteClass(record)"><DeleteOutlined/></a-button></span></a-tooltip></a-space></template></a-table-column></a-table></a-card>
  <a-card class="panel-card" :bordered="false"><a-empty v-if="!classId" description="请先创建教学班"/>
    <template v-else>
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
    </template>
  </a-card>
</template>

<style scoped>
.class-portfolio-toolbar{flex-wrap:wrap;gap:14px}
</style>
