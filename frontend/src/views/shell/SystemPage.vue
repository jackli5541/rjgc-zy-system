<script setup>
import { useShellContext } from '../../shellContext'
const { audits, auditSearch, auditPage, auditPageSize, auditTotal, loading, formatTime, actionLabel, objectLabel, searchAudits, changeAuditPage } = useShellContext()
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">运行管理</div><h1>系统与审计</h1><p>关键业务操作不可修改。</p></div></div>
  <div class="audit-toolbar"><a-input-search v-model:value="auditSearch" allow-clear placeholder="搜索操作者、IP、操作或对象" enter-button="查询" @search="searchAudits"/></div>
  <a-table :data-source="audits" :loading="loading" :pagination="{current:auditPage,pageSize:auditPageSize,total:auditTotal,showSizeChanger:false,showTotal:total=>`共 ${total} 条`}" row-key="id" @change="pagination=>changeAuditPage(pagination.current)"><a-table-column title="时间"><template #default="{record}">{{formatTime(record.created_at)}}</template></a-table-column><a-table-column title="操作者" data-index="actor"/><a-table-column title="IP 地址"><template #default="{record}">{{record.ip_address||'-'}}</template></a-table-column><a-table-column title="操作"><template #default="{record}">{{actionLabel(record.action)}}</template></a-table-column><a-table-column title="对象"><template #default="{record}">{{objectLabel(record.object_type)}}</template></a-table-column><template #emptyText><a-empty :description="auditSearch?'未找到匹配的审计记录':'暂无审计记录'"/></template></a-table>
</template>
