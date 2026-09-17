<script setup>
import { EditOutlined, EyeOutlined, FileTextOutlined, InboxOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'
const { role, activeClasses, assignments, openAssignmentCreate, assignmentStateClass, openAssignment, continueGrading, formatTime, assignmentCountdown, statusLabel } = useShellContext()
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'教学任务':'学习任务'}}</div><h1>{{role==='TEACHER'?'作业管理':'我的作业'}}</h1><p>{{role==='TEACHER'?'发布作业、维护附件并查看全班提交情况。':'查看作业要求，管理草稿并完成正式提交。'}}</p></div><a-button v-if="role==='TEACHER'" type="primary" :disabled="!activeClasses.length" @click="openAssignmentCreate"><PlusOutlined /> 新建作业</a-button></div>
  <a-empty v-if="!assignments.length" description="暂无作业"/>
  <a-card v-for="item in assignments" :key="item.id" class="assignment-row" :class="assignmentStateClass(item)" :bordered="false" @click="openAssignment(item,role==='TEACHER'?'submission':'details')"><div class="assignment-icon blue"><FileTextOutlined/></div><div class="assignment-main"><div class="assignment-heading"><h3>{{item.title}}</h3><a-tag v-if="role==='STUDENT'&&item.submission_status==='SUBMITTED'">已完成</a-tag><a-tag v-else-if="role==='STUDENT'&&new Date(item.due_at)<=new Date()" color="error">已逾期</a-tag></div><div class="rich-text compact" v-html="item.description"></div><span>截止 {{formatTime(item.due_at)}}</span></div><div class="assignment-end"><strong class="assignment-countdown" :class="assignmentCountdown(item).state">{{assignmentCountdown(item).label}}</strong><div class="assignment-tags"><a-tag>{{item.submitter_type==='INDIVIDUAL'?'个人作业':'小组作业'}}</a-tag><a-tag :color="item.status==='PUBLISHED'?'green':'default'">{{statusLabel(item.status)}}</a-tag></div><div v-if="role==='TEACHER'" class="assignment-entry-actions" @click.stop><a-button @click="openAssignment(item,'details')"><EyeOutlined/> 详情</a-button><a-button @click="openAssignment(item,'submission')"><InboxOutlined/> 提交情况</a-button><a-button v-if="item.submitter_type==='INDIVIDUAL'" type="primary" @click="continueGrading(item)"><EditOutlined/> 继续批改</a-button></div></div></a-card>
</template>
