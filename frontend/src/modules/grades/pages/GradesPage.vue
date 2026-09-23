<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { DatabaseOutlined, DownloadOutlined, EyeOutlined, FileTextOutlined, FormOutlined, InboxOutlined, TeamOutlined, TrophyOutlined, UserOutlined } from '@ant-design/icons-vue'
import { api, exportArchive } from '../../../api'
import { useShellContext } from '../../../shellContext'

const { role, classId, activeClasses, grades, gradeAssignments, selectedGradeAssignmentId, statusLabel, gradeSourceLabel, downloadExport, openStudentFeedback } = useShellContext()
const className = computed(() => activeClasses.value.find(item => item.id === classId.value)?.name || '')
const gradesTab = ref('overview')
const overviewItems = ref([])
const overviewLoading = ref(false)
async function loadGradeOverview() {
  if (!classId.value) { overviewItems.value = []; return }
  overviewLoading.value = true
  try {
    const data = await api(`/classes/${classId.value}/grade-overview`)
    overviewItems.value = data.items
  } catch (error) {
    message.error(error.message || '成绩总览加载失败')
  } finally {
    overviewLoading.value = false
  }
}
onMounted(loadGradeOverview)
watch(classId, loadGradeOverview)
async function saveAttendance(record, value) {
  try {
    await api(`/classes/${classId.value}/students/${record.student_id}/attendance-score`, { method: 'PUT', body: JSON.stringify({ score: value ?? null }) })
    await loadGradeOverview()
  } catch (error) {
    message.error(error.message || '考勤分保存失败')
  }
}
function gradeTagColor(grade) {
  if (grade === 'A' || grade === 'B') return 'green'
  if (grade === 'C') return 'blue'
  if (grade === 'D') return 'orange'
  if (grade === 'E') return 'red'
  return 'default'
}
const gradingStatusColor = status => status === 'PENDING_REASSESSMENT' ? 'blue' : status === 'PENDING_ASSESSMENT' ? 'orange' : 'default'
const archivingClass = ref(false)
// 班级层面的学业画像：均分/及格率/优秀率只在"已能算出综合成绩"的学生里统计，
// 分母另外标出来，避免学期中大量学生还缺分项时把比率稀释成误导性的低值。
const classSummary = computed(() => {
  const scored = overviewItems.value.map(item => item.composite_score).filter(score => score !== null && score !== undefined)
  if (!scored.length) return { studentCount: overviewItems.value.length, scored: 0, average: null, passRate: null, excellentRate: null }
  const sum = scored.reduce((total, score) => total + score, 0)
  return {
    studentCount: overviewItems.value.length,
    scored: scored.length,
    average: Math.round((sum / scored.length) * 10) / 10,
    passRate: Math.round((scored.filter(score => score >= 60).length / scored.length) * 100),
    excellentRate: Math.round((scored.filter(score => score >= 90).length / scored.length) * 100)
  }
})

const summaryCaption = computed(() => {
  const { studentCount, scored } = classSummary.value
  if (!studentCount) return '当前教学班暂无学生'
  if (!scored) return `${studentCount} 名学生，暂无人可结算综合成绩（分项数据未齐）`
  return `均分 / 及格率 / 优秀率按已结算综合成绩的 ${scored} 人计算，共 ${studentCount} 人`
})

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
      <div class="archive-overview-main"><span class="archive-mark"><DatabaseOutlined/></span><div><h2>全班学生档案</h2><p class="archive-caption">{{summaryCaption}}</p></div></div>
      <div class="archive-metrics" aria-label="全班学业概况"><div><span>班级人数</span><strong>{{classSummary.studentCount}}</strong></div><div><span>均分</span><strong>{{classSummary.average ?? '—'}}</strong></div><div><span>及格率</span><strong>{{classSummary.passRate === null ? '—' : `${classSummary.passRate}%`}}</strong></div><div><span>优秀率</span><strong>{{classSummary.excellentRate === null ? '—' : `${classSummary.excellentRate}%`}}</strong></div></div>
      <a-button type="primary" size="large" :loading="archivingClass" @click="downloadClassArchive"><InboxOutlined/> 导出全班档案 ZIP</a-button>
    </section>

    <section class="grade-export-section grades-tabs-card">
      <a-tabs v-model:activeKey="gradesTab" class="grades-tabs" :animated="{inkBar:true,tabPane:true}">
        <a-tab-pane key="overview">
          <template #tab><span><TrophyOutlined/> 成绩总览</span></template>
          <p class="overview-hint">按导入名单顺序排列；平时成绩20%=平时作业10%+考勤10%（考勤为手动录入，直接在下面输入框里填写）；实验成绩30%；期末成绩50%来自大作业5个阶段评分。任一分项暂无数据时显示"—"。</p>
          <a-table :data-source="overviewItems" :loading="overviewLoading" row-key="student_id" size="small" :pagination="false">
            <a-table-column title="学号" data-index="student_no" :width="130"/>
            <a-table-column title="姓名" data-index="name" :width="100"/>
            <a-table-column title="班级" :width="110"><template #default>{{className}}</template></a-table-column>
            <a-table-column title="组名"><template #default="{record}">{{record.team_name || '未分组'}}</template></a-table-column>
            <a-table-column title="平时成绩(20%)" :width="190">
              <template #default="{record}">
                <div class="routine-score-cell">
                  <strong>{{record.routine_score ?? '—'}}</strong>
                  <span class="routine-score-sub">作业 {{record.homework_component ?? '—'}}</span>
                  <a-input-number class="attendance-input" size="small" :min="0" :max="10" :step="0.5" :precision="1" :value="record.attendance_component" placeholder="考勤" @change="value => saveAttendance(record, value)"/>
                </div>
              </template>
            </a-table-column>
            <a-table-column title="实验成绩(30%)"><template #default="{record}">{{record.lab_score ?? '—'}}</template></a-table-column>
            <a-table-column title="期末成绩(50%)"><template #default="{record}">{{record.capstone_score ?? '—'}}</template></a-table-column>
            <a-table-column title="综合成绩"><template #default="{record}"><strong>{{record.composite_score ?? '—'}}</strong></template></a-table-column>
            <a-table-column title="等级"><template #default="{record}"><a-tag v-if="record.grade" :color="gradeTagColor(record.grade)">{{record.grade}}</a-tag><span v-else>—</span></template></a-table-column>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="export">
          <template #tab><span><DownloadOutlined/> 单次作业导出</span></template>
          <div class="export-toolbar"><a-select v-model:value="selectedGradeAssignmentId" allow-clear placeholder="选择个人作业" :options="gradeAssignments.map(item=>({value:item.id,label:item.title}))"/></div>
          <div v-if="selectedGradeAssignmentId" class="assignment-export-actions">
            <div class="assignment-export-status"><FileTextOutlined/><div><strong>{{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.title}}</strong><span>已提交 {{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.submitted || 0}} / {{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.total || 0}} · 已评分 {{gradeAssignments.find(item=>item.id===selectedGradeAssignmentId)?.graded || 0}}</span></div></div>
            <a-space wrap><a-button @click="downloadExport('grades')"><TrophyOutlined/> 成绩明细 XLSX</a-button><a-button @click="downloadExport('grades','csv')"><DownloadOutlined/> CSV</a-button><a-button type="primary" ghost @click="downloadAssignmentFiles"><InboxOutlined/> 学生作业原文件 ZIP</a-button></a-space>
          </div>
          <a-empty v-else description="请先选择需要导出的个人作业"/>
          <div v-if="gradeAssignments.length" class="grade-coverage-list">
            <div class="coverage-head"><span>作业</span><span>提交</span><span>评分</span><span>待处理</span></div>
            <button v-for="item in gradeAssignments" :key="item.id" type="button" :class="{active:selectedGradeAssignmentId===item.id}" @click="selectedGradeAssignmentId=item.id"><span><strong>{{item.title}}</strong><small>截止 {{new Date(item.due_at).toLocaleString('zh-CN',{hour12:false})}}</small></span><span>{{item.submitted}} / {{item.total}}</span><span>{{item.graded}} / {{item.total}}</span><a-tag :color="item.pending?'gold':'green'">{{item.pending ? `${item.pending} 人` : '已完成'}}</a-tag></button>
          </div>
        </a-tab-pane>

        <a-tab-pane key="data">
          <template #tab><span><DatabaseOutlined/> 基础数据与导出</span></template>
          <div class="data-export-list">
            <div class="data-export-row"><span class="data-export-icon blue"><UserOutlined/></span><div><strong>成员名单</strong></div><a-space><a-button @click="downloadExport('members')">XLSX</a-button><a-button type="text" @click="downloadExport('members','csv')">CSV</a-button></a-space></div>
            <div class="data-export-row"><span class="data-export-icon purple"><TeamOutlined/></span><div><strong>小组名单</strong></div><a-space><a-button @click="downloadExport('teams')">XLSX</a-button><a-button type="text" @click="downloadExport('teams','csv')">CSV</a-button></a-space></div>
            <div class="data-export-row"><span class="data-export-icon cyan"><FormOutlined/></span><div><strong>互评记录</strong></div><a-space><a-button @click="downloadExport('reviews')">XLSX</a-button><a-button type="text" @click="downloadExport('reviews','csv')">CSV</a-button></a-space></div>
          </div>
        </a-tab-pane>
      </a-tabs>
    </section>
  </template>
  <template v-else>
    <a-empty v-if="!grades.length" description="暂无成绩"/>
    <a-table v-else :data-source="grades" row-key="id"><a-table-column title="作业" data-index="assignment_title"/><a-table-column title="类型"><template #default="{record}">{{record.submitter_type==='TEAM'?'小组作业':'个人作业'}}</template></a-table-column><a-table-column title="互评成绩"><template #default="{record}"><span v-if="record.submitter_type==='TEAM'">-</span><template v-else>{{record.peer_grade||'-'}}<span v-if="record.peer_review_count">（{{record.peer_review_count}} 人）</span></template></template></a-table-column><a-table-column title="教师评分"><template #default="{record}">{{record.teacher_grade?.grade||'-'}}</template></a-table-column><a-table-column title="最终成绩"><template #default="{record}"><a-tag v-if="record.final_grade" :color="record.grade_source==='SYSTEM'?'red':'green'">{{record.final_grade}}</a-tag><a-tag v-else :color="gradingStatusColor(record.grading_status)">{{statusLabel(record.grading_status)}}</a-tag></template></a-table-column><a-table-column title="来源"><template #default="{record}">{{gradeSourceLabel(record.grade_source)}}</template></a-table-column><a-table-column title="反馈"><template #default="{record}"><a-space direction="vertical" size="small"><a-button v-if="record.teacher_grade&&record.files?.length" type="link" @click="openStudentFeedback(record)"><EyeOutlined/> 查看教师反馈{{record.peer_feedbacks?.length ? '与互评' : ''}}</a-button><a-button v-else v-for="feedback in record.peer_feedbacks||[]" :key="feedback.id" type="link" @click="openStudentFeedback(record,feedback)"><EyeOutlined/> {{feedback.evaluator_name}}的互评</a-button><span v-if="!record.teacher_grade&&!record.peer_feedbacks?.length">-</span></a-space></template></a-table-column></a-table>
  </template>
</template>
