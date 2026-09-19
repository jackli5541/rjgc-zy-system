<script setup>
import { useShellContext } from '../../shellContext'
const { audits, auditSearch, auditSemester, auditClassId, auditActorRole, auditSearched, auditSemesterOptions, auditClassOptions, auditPage, auditPageSize, auditTotal, loading, formatTime, actionLabel, objectLabel, roleLabel, searchAudits, changeAuditSemester, changeAuditPage } = useShellContext()
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">运行管理</div><h1>系统与审计</h1><p>关键业务操作不可修改。</p></div></div>
  <div class="audit-toolbar">
    <a-select v-model:value="auditSemester" :options="[{value:'ALL',label:'全部学期'},...auditSemesterOptions]" @change="changeAuditSemester"/>
    <a-select v-model:value="auditClassId" :options="[{value:'ALL',label:'全部教学班'},...auditClassOptions]" @change="searchAudits"/>
    <a-select v-model:value="auditActorRole" :options="[{value:'ALL',label:'全部角色'},{value:'TEACHER',label:'教师'},{value:'STUDENT',label:'学生'}]" @change="searchAudits"/>
    <a-input-search v-model:value="auditSearch" allow-clear placeholder="搜索操作者、班级、IP、操作或对象" enter-button="查询" @search="searchAudits"/>
  </div>
  <a-empty v-if="!auditSearched" description="请输入条件并点击查询后查看审计记录" />
  <a-table v-else :data-source="audits" :loading="loading" :scroll="{x:1050}" :pagination="{current:auditPage,pageSize:auditPageSize,total:auditTotal,showSizeChanger:false,showTotal:total=>`共 ${total} 条`}" row-key="id" @change="pagination=>changeAuditPage(pagination.current)"><a-table-column title="时间" :width="180"><template #default="{record}">{{formatTime(record.created_at)}}</template></a-table-column><a-table-column title="教学班" :width="220"><template #default="{record}">{{record.class_name ? `${record.class_semester} · ${record.class_name}` : '系统级'}}</template></a-table-column><a-table-column title="角色" :width="80"><template #default="{record}">{{roleLabel(record.actor_role)}}</template></a-table-column><a-table-column title="操作者" data-index="actor" :width="120"/><a-table-column title="IP 地址" :width="140"><template #default="{record}">{{record.ip_address||'-'}}</template></a-table-column><a-table-column title="操作" :width="150"><template #default="{record}">{{actionLabel(record.action)}}</template></a-table-column><a-table-column title="对象" :width="120"><template #default="{record}">{{objectLabel(record.object_type)}}</template></a-table-column><template #emptyText><a-empty description="未找到匹配的审计记录"/></template></a-table>
</template>
