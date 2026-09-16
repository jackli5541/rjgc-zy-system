<script setup>
import { useShellContext } from '../../shellContext'
const { audits, formatTime, actionLabel, objectLabel } = useShellContext()
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">运行管理</div><h1>系统与审计</h1><p>关键业务操作不可修改。</p></div></div>
  <a-empty v-if="!audits.length" description="暂无审计记录"/>
  <a-table v-else :data-source="audits" row-key="id"><a-table-column title="时间"><template #default="{record}">{{formatTime(record.created_at)}}</template></a-table-column><a-table-column title="操作者" data-index="actor"/><a-table-column title="操作"><template #default="{record}">{{actionLabel(record.action)}}</template></a-table-column><a-table-column title="对象"><template #default="{record}">{{objectLabel(record.object_type)}}</template></a-table-column></a-table>
</template>
