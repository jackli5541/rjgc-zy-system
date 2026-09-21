<script setup>
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { DatabaseOutlined, DownloadOutlined, EyeOutlined, FileTextOutlined, FormOutlined, InboxOutlined, TeamOutlined, TrophyOutlined, UserOutlined } from '@ant-design/icons-vue'
import { exportArchive } from '../../api'
import { useShellContext } from '../../shellContext'

const { role, classId, grades, gradeAssignments, selectedGradeAssignmentId, statusLabel, gradeSourceLabel, downloadExport, openStudentFeedback } = useShellContext()
const gradingStatusColor = status => status === 'PENDING_REASSESSMENT' ? 'blue' : status === 'PENDING_ASSESSMENT' ? 'orange' : 'default'
const archivingClass = ref(false)
const archiveSummary = computed(() => ({
  assignmentCount: gradeAssignments.value.length,
  studentCount: Math.max(0, ...gradeAssignments.value.map(item => item.total || 0)),
  pending: gradeAssignments.value.reduce((sum, item) => sum + (item.pending || 0), 0)
}))

async function downloadClassArchive() {
  if (!classId.value || archivingClass.value) return
  archivingClass.value = true
  try {
    await exportArchive(`/classes/${classId.value}/portfolio.zip`)
    message.success('全班学生档案已开始下载')
  } catch (error) {
    message.error(error.message || '档案导出失败')
  } finally {
    archivingClass.value = false
  }
}

async function downloadAssignmentFiles() {
  if (!selectedGradeAssignmentId.value) return
  try {
    await exportArchive(`/assignments/${selectedGradeAssignmentId.value}/download.zip`)
    message.success('导出文件已生成')
  } catch (error) {
    message.error(error.message || '作业导出失败')
  }
}
</script>

<template>
  <div class="page-title"><div><h1>{{role==='TEACHER'?'成绩与导出':'成绩与反馈'}}</h1></div></div>
  <template v-if="role==='TEACHER'">
    <section class="archive-overview">
      <div class="archive-overview-main"><span class="archive-mark"><DatabaseOutlined/></span><div><h2>全班学生档案</h2></div></div>
      <div class="archive-metrics" aria-label="当前归档范围"><div><span>学生</span><strong>{{archiveSummary.studentCount}}</strong></div><div><span>个人作业</span><strong>{{archiveSummary.assignmentCount}}</strong></div><div><span>待评分</span><strong :class="{warning:archiveSummary.pending}">{{archiveSummary.pending}}</strong></div></div>
      <a-button type="primary" size="large" :loading="archivingClass" @click="downloadClassArchive"><InboxOutlined/> 导出全班档案 ZIP</a-button>
    </section>

    <section class="grade-export-section">
      <div class="export-section-heading"><div><h2>单次作业导出</h2></div><a-select v-model:value="selectedGradeAssignmentId" allow-clear placeholder="选择个人作业" :options="gradeAssignments.map(item=>({value:item.id,label:item.title}))"/></div>
      <div v-if="selectedGradeAssignmentId" class="assignment-export-actions">
        <div class="assignment-export-status"><FileTextOutlined/><div><strong>{{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.title}}</strong><span>已提交 {{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.submitted || 0}} / {{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.total || 0}} · 已评分 {{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.graded || 0}}</span></div></div>
        <a-space wrap><a-button @click="downloadExport('grades')"><TrophyOutlined/> 成绩明细 XLSX</a-button><a-button @click="downloadExport('grades','csv')"><DownloadOutlined/> CSV</a-button><a-button type="primary" ghost @click="downloadAssignmentFiles"><InboxOutlined/> 学生作业原文件 ZIP</a-button></a-space>
      </div>
      <a-empty v-else description="请先选择需要导出的个人作业"/>
      <div v-if="gradeAssignments.length" class="grade-coverage-list">
        <div class="coverage-head"><span>作业</span><span>提交</span><span>评分</span><span>待处理</span></div>
        <button v-for="item in gradeAssignments" :key="item.id" type="button" :class="{active:selectedGradeAssignmentId===item.id}" @click="selectedGradeAssignmentId=item.id"><span><strong>{{item.title}}</strong><small>截止 {{new Date(item.due_at).toLocaleString('zh-CN',{hour12:false})}}</small></span><span>{{item.submitted}} / {{item.total}}</span><span>{{item.graded}} / {{item.total}}</span><a-tag :color="item.pending?'gold':'green'">{{item.pending ? `${item.pending} 人` : '已完成'}}</a-tag></button>
      </div>
    </section>

    <section class="grade-export-section compact">
      <div class="export-section-heading"><div><h2>基础数据与评价记录</h2></div></div>
      <div class="data-export-list">
        <div class="data-export-row"><span class="data-export-icon blue"><UserOutlined/></span><div><strong>成员名单</strong></div><a-space><a-button @click="downloadExport('members')">XLSX</a-button><a-button type="text" @click="downloadExport('members','csv')">CSV</a-button></a-space></div>
        <div class="data-export-row"><span class="data-export-icon purple"><TeamOutlined/></span><div><strong>小组名单</strong></div><a-space><a-button @click="downloadExport('teams')">XLSX</a-button><a-button type="text" @click="downloadExport('teams','csv')">CSV</a-button></a-space></div>
        <div class="data-export-row"><span class="data-export-icon cyan"><FormOutlined/></span><div><strong>互评记录</strong></div><a-space><a-button @click="downloadExport('reviews')">XLSX</a-button><a-button type="text" @click="downloadExport('reviews','csv')">CSV</a-button></a-space></div>
      </div>
    </section>
  </template>
  <template v-else>
    <a-empty v-if="!grades.length" description="暂无成绩"/>
    <a-table v-else :data-source="grades" row-key="id"><a-table-column title="作业" data-index="assignment_title"/><a-table-column title="类型"><template #default="{record}">{{record.submitter_type==='TEAM'?'小组作业':'个人作业'}}</template></a-table-column><a-table-column title="互评成绩"><template #default="{record}"><span v-if="record.submitter_type==='TEAM'">-</span><template v-else>{{record.peer_grade||'-'}}<span v-if="record.peer_review_count">（{{record.peer_review_count}} 人）</span></template></template></a-table-column><a-table-column title="教师评分"><template #default="{record}">{{record.teacher_grade?.grade||'-'}}</template></a-table-column><a-table-column title="最终成绩"><template #default="{record}"><a-tag v-if="record.final_grade" :color="record.grade_source==='SYSTEM'?'red':'green'">{{record.final_grade}}</a-tag><a-tag v-else :color="gradingStatusColor(record.grading_status)">{{statusLabel(record.grading_status)}}</a-tag></template></a-table-column><a-table-column title="来源"><template #default="{record}">{{gradeSourceLabel(record.grade_source)}}</template></a-table-column><a-table-column title="反馈"><template #default="{record}"><a-space direction="vertical" size="small"><a-button v-if="record.teacher_grade&&record.files?.length" type="link" @click="openStudentFeedback(record)"><EyeOutlined/> 查看教师反馈{{record.peer_feedbacks?.length ? '与互评' : ''}}</a-button><a-button v-else v-for="feedback in record.peer_feedbacks||[]" :key="feedback.id" type="link" @click="openStudentFeedback(record,feedback)"><EyeOutlined/> {{feedback.evaluator_name}}的互评</a-button><span v-if="!record.teacher_grade&&!record.peer_feedbacks?.length">-</span></a-space></template></a-table-column></a-table>
  </template>
</template>
