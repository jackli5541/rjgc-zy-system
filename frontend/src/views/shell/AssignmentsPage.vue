<script setup>
import { EditOutlined, EyeOutlined, FileTextOutlined, InboxOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'
import { computed } from 'vue'
const { role, activeClasses, assignments, openAssignmentCreate, assignmentStateClass, openAssignment, openStudentAssignment, continueGrading, formatTime, assignmentCountdown, statusLabel } = useShellContext()
const mascotAssignmentId = computed(() => role.value === 'STUDENT' ? assignments.value[0]?.id : null)
const progressStatusLabels = {
  NO_ROSTER: '暂无学生',
  PENDING_SUBMISSION: '待提交',
  PENDING_REVIEW: '待互评',
  PENDING_TEACHER_GRADING: '待教师评分',
  COMPLETED: '全部完成'
}
function assignmentProgress(item) {
  return item.progress || { expected_count: 0, submitted_count: 0, teacher_graded_count: 0, review_enabled: false, review_assigned_count: 0, review_completed_count: 0, completion_status: 'NO_ROSTER' }
}
function progressStatusLabel(item) { return progressStatusLabels[assignmentProgress(item).completion_status] || '进行中' }
function progressStatusClass(item) { return assignmentProgress(item).completion_status.toLowerCase().replaceAll('_', '-') }
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'教学任务':'学习任务'}}</div><h1>{{role==='TEACHER'?'作业管理':'我的作业'}}</h1><p>{{role==='TEACHER'?'发布作业、维护附件并查看全班提交情况。':'查看作业要求，管理草稿并完成正式提交。'}}</p></div><a-button v-if="role==='TEACHER'" type="primary" :disabled="!activeClasses.length" @click="openAssignmentCreate"><PlusOutlined /> 新建作业</a-button></div>
  <a-empty v-if="!assignments.length" description="暂无作业"/>
  <a-card v-for="item in assignments" :key="item.id" class="assignment-row" :class="[assignmentStateClass(item), { 'assignment-mascot-row': item.id === mascotAssignmentId }]" :bordered="false" @click="role==='TEACHER'?openAssignment(item,'submission'):openStudentAssignment(item)"><img v-if="item.id === mascotAssignmentId" class="assignment-mascot" src="/assignment-mascot.png" alt="" aria-hidden="true" draggable="false" /><div class="assignment-icon blue"><FileTextOutlined/></div><div class="assignment-main"><div class="assignment-heading"><h3>{{item.title}}</h3><a-tag v-if="role==='STUDENT'&&item.submission_status==='SUBMITTED'">已完成</a-tag><a-tag v-else-if="role==='STUDENT'&&new Date(item.due_at)<=new Date()" color="error">已逾期</a-tag></div><div class="rich-text compact" v-html="item.description"></div><span>截止 {{formatTime(item.due_at)}}</span></div><div class="assignment-end"><strong class="assignment-countdown" :class="assignmentCountdown(item).state">{{assignmentCountdown(item).label}}</strong><div class="assignment-tags"><a-tag>{{item.submitter_type==='INDIVIDUAL'?'个人作业':'小组作业'}}</a-tag><a-tag :color="item.status==='PUBLISHED'?'green':'default'">{{statusLabel(item.status)}}</a-tag><a-tag v-if="role==='TEACHER'" class="assignment-completion-tag" :class="progressStatusClass(item)">{{progressStatusLabel(item)}}</a-tag></div><div v-if="role==='TEACHER'" class="assignment-progress" @click.stop><div class="assignment-progress-item"><span>提交</span><strong>{{assignmentProgress(item).submitted_count}}<small>/{{assignmentProgress(item).expected_count}}</small></strong></div><div v-if="assignmentProgress(item).review_enabled && assignmentProgress(item).review_assigned_count" class="assignment-progress-item"><span>互评</span><strong>{{assignmentProgress(item).review_completed_count}}<small>/{{assignmentProgress(item).review_assigned_count}}</small></strong></div><div v-else class="assignment-progress-item disabled"><span>互评</span><strong>{{assignmentProgress(item).review_enabled ? '暂无可互评' : '未开启'}}</strong></div><div class="assignment-progress-item"><span>教师已评</span><strong>{{assignmentProgress(item).teacher_graded_count}}<small>/{{assignmentProgress(item).submitted_count}}</small></strong></div></div><div v-if="role==='TEACHER'" class="assignment-entry-actions" @click.stop><a-button @click="openAssignment(item,'details')"><EyeOutlined/> 详情</a-button><a-button @click="openAssignment(item,'submission')"><InboxOutlined/> 提交情况</a-button><a-button type="primary" @click="continueGrading(item)"><EditOutlined/> 继续批改</a-button></div></div></a-card>
</template>

<style scoped>
.assignment-progress {
  display: grid;
  grid-template-columns: repeat(3, minmax(58px, 1fr));
  gap: 1px;
  width: 100%;
  overflow: hidden;
  border: 1px solid #e4ebf1;
  border-radius: 6px;
  background: #e4ebf1;
  text-align: center;
}
.assignment-progress-item { min-width: 0; padding: 6px 8px; background: #f8fafc; }
.assignment-progress-item span,
.assignment-progress-item strong { display: block; }
.assignment-progress-item span { color: #7d8b99; font-size: 10px; white-space: nowrap; }
.assignment-progress-item strong { margin-top: 2px; color: #26394d; font-size: 15px; line-height: 1.15; }
.assignment-progress-item small { color: #8996a3; font-size: 10px; font-weight: 500; }
.assignment-progress-item.disabled { background: #f1f4f6; }
.assignment-progress-item.disabled span,
.assignment-progress-item.disabled strong { color: #9aa6b1; }
.assignment-completion-tag { font-weight: 600; }
.assignment-completion-tag.pending-submission { color: #9a661e; border-color: #ecd4a8; background: #fff8e9; }
.assignment-completion-tag.pending-review { color: #7653a7; border-color: #d9c8ef; background: #f7f1ff; }
.assignment-completion-tag.pending-teacher-grading { color: #176b78; border-color: #b9dfe2; background: #effafa; }
.assignment-completion-tag.completed { color: #2d7d4e; border-color: #b9ddc6; background: #e9f8ed; }
.assignment-completion-tag.no-roster { color: #718096; border-color: #dbe2e8; background: #f5f7f9; }
.assignment-mascot-row {
  position: relative;
  isolation: isolate;
  overflow: visible;
}
.assignment-mascot-row :deep(.ant-card-body) {
  position: relative;
  background: inherit;
  border-radius: inherit;
  isolation: isolate;
}
.assignment-mascot-row :deep(.ant-card-body) > :not(.assignment-mascot) {
  position: relative;
  z-index: 1;
}
.assignment-mascot-row :deep(.ant-card-body)::before {
  content: '';
  display: block;
  position: absolute;
  inset: 0;
  z-index: 0;
  background: inherit;
  border-radius: inherit;
}
.assignment-mascot {
  position: absolute;
  right: 38px;
  top: 0;
  z-index: -1;
  width: auto;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
  user-select: none;
  opacity: 0;
  transform: translateY(0);
  transition: transform 650ms cubic-bezier(.22, 1, .36, 1), opacity 250ms ease;
}
@media (hover: hover) and (pointer: fine) {
  .assignment-mascot-row:hover .assignment-mascot {
    opacity: 1;
    transform: translateY(-68%);
  }
}
@media (max-width: 760px) {
  .assignment-mascot { right: 20px; }
  .assignment-progress { grid-template-columns: repeat(3, minmax(64px, 1fr)); }
}
@media (prefers-reduced-motion: reduce) {
  .assignment-mascot { transition: none; }
}
</style>
