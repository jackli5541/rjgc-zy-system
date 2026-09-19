<script setup>
import { FormOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'
const { campaigns, formatTime, openCampaign } = useShellContext()
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">组内作品互评</div><h1>作品互评</h1><p>选择本组已提交作业的成员，按 A–E 五档进行评价。</p></div></div>
  <a-empty v-if="!campaigns.length" description="暂无可评价的组员提交"/>
  <a-card v-for="item in campaigns" :key="item.assignment_id" class="assignment-row" :bordered="false" @click="openCampaign(item)"><div class="assignment-icon cyan"><FormOutlined/></div><div class="assignment-main"><div class="assignment-heading"><h3>{{item.assignment_title}}</h3><a-tag v-if="item.pending_count===0" color="green">当前已完成</a-tag></div><p>本组已有 {{item.available_count}} 人提交，点击查看评价明细</p><div class="assignment-meta"><span>仅限组内互评</span><span>作业截止 {{formatTime(item.due_at)}}</span></div></div><div class="assignment-end"><strong>{{item.pending_count ? `待评价 ${item.pending_count} 人` : '可更新评价'}}</strong></div></a-card>
</template>
