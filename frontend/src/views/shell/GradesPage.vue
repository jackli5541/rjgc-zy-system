<script setup>
import { DownloadOutlined, EyeOutlined, FormOutlined, TeamOutlined, TrophyOutlined, UserOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../shellContext'

const { role, grades, gradeAssignments, selectedGradeAssignmentId, statusLabel, gradeSourceLabel, downloadExport, openStudentFeedback } = useShellContext()
</script>

<template>
  <div class="page-title"><div><div class="eyebrow">{{role==='TEACHER'?'数据归档':'学习成果'}}</div><h1>{{role==='TEACHER'?'成绩与导出':'成绩与反馈'}}</h1><p>{{role==='TEACHER'?'集中导出当前教学班的成员、小组、互评和成绩数据。':'查看组内互评成绩，以及教师评分覆盖后的最终成绩。'}}</p></div></div>
  <template v-if="role==='TEACHER'">
    <div class="export-grid">
      <section class="export-item"><div class="export-item-icon blue"><UserOutlined/></div><div><h2>成员名单</h2><p>导出学号、姓名、状态和所属小组。</p></div><a-space><a-button @click="downloadExport('members')"><DownloadOutlined/> XLSX</a-button><a-button @click="downloadExport('members','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
      <section class="export-item"><div class="export-item-icon purple"><TeamOutlined/></div><div><h2>小组名单</h2><p>导出小组、组长、人数、选题和状态。</p></div><a-space><a-button @click="downloadExport('teams')"><DownloadOutlined/> XLSX</a-button><a-button @click="downloadExport('teams','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
      <section class="export-item"><div class="export-item-icon cyan"><FormOutlined/></div><div><h2>互评记录</h2><p>导出评价人、被评价人、得分、状态和评语。</p></div><a-space><a-button @click="downloadExport('reviews')"><DownloadOutlined/> XLSX</a-button><a-button @click="downloadExport('reviews','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
      <section class="export-item export-grade-item"><div class="export-item-icon green"><TrophyOutlined/></div><div><h2>作业成绩</h2><p>选择个人作业，导出全部学生的提交与评分状态。</p><a-select v-model:value="selectedGradeAssignmentId" allow-clear placeholder="选择个人作业" :options="gradeAssignments.map(item=>({value:item.id,label:`${item.title} · 已评分 ${item.graded}/${item.total}`}))"/></div><a-space><a-button :disabled="!selectedGradeAssignmentId" @click="downloadExport('grades')"><DownloadOutlined/> XLSX</a-button><a-button :disabled="!selectedGradeAssignmentId" @click="downloadExport('grades','csv')"><DownloadOutlined/> CSV</a-button></a-space></section>
    </div>
  </template>
  <template v-else>
    <a-empty v-if="!grades.length" description="暂无成绩"/>
    <a-table v-else :data-source="grades" row-key="id"><a-table-column title="作业" data-index="assignment_title"/><a-table-column title="互评成绩"><template #default="{record}">{{record.peer_grade||'-'}}<span v-if="record.peer_review_count">（{{record.peer_review_count}} 人）</span></template></a-table-column><a-table-column title="教师评分"><template #default="{record}">{{record.teacher_grade?.grade||'-'}}</template></a-table-column><a-table-column title="最终成绩"><template #default="{record}"><a-tag v-if="record.final_grade" :color="record.grade_source==='SYSTEM'?'red':'green'">{{record.final_grade}}</a-tag><a-tag v-else color="gold">{{statusLabel(record.grading_status)}}</a-tag></template></a-table-column><a-table-column title="来源"><template #default="{record}">{{gradeSourceLabel(record.grade_source)}}</template></a-table-column><a-table-column title="反馈"><template #default="{record}"><a-space direction="vertical" size="small"><a-button v-if="record.teacher_grade&&record.files?.length" type="link" @click="openStudentFeedback(record)"><EyeOutlined/> 查看教师反馈</a-button><a-button v-for="feedback in record.peer_feedbacks||[]" :key="feedback.id" type="link" @click="openStudentFeedback(record,feedback)"><EyeOutlined/> {{feedback.evaluator_name}}的互评</a-button><span v-if="!record.teacher_grade&&!record.peer_feedbacks?.length">-</span></a-space></template></a-table-column></a-table>
  </template>
</template>
