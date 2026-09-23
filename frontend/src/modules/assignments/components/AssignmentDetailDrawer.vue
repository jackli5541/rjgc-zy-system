<script setup>
import { api } from '../../../api'
import AssignmentMaterials from './AssignmentMaterials.vue'
import OnlineMarkdownWorkspace from '../../../shared/components/OnlineMarkdownWorkspace.vue'
import { ArrowLeftOutlined, CheckCircleOutlined, DeleteOutlined, DownloadOutlined, EditOutlined, ExpandOutlined, EyeOutlined, InboxOutlined, RightOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { useShellContext } from '../../../shellContext'

const { assignmentAttachments, assignmentDetailTab, assignmentDrawerAnimating, assignmentDrawerExpanded, assignmentDrawerResizing, assignmentDrawerWidth, assignmentIsUpdate, assignmentSubmitted, assignmentTypeLabel, boardFilter, boardQuery, boardTeamFilter, boardTeamOptions, canEditAssignment, canManageTeamSubmission, canSubmitAssignment, changeAssignmentDetailTab, classId, closeAssignment, closeAssignmentDrawer, deleteAssignment, deleteDraft, deleteSelectedMaterials, deletingMaterials, downloadAssignmentSubmissions, exportingAssignment, focusSubmissionStatus, formatTime, gradeSourceLabel, grades, gradingStatusColor, groupedBoard, materialTypeOptions, onlineWorkspace, onlineWorkspaceData, openAssignmentEdit, openFilePreview, openSubmissionDetail, publishAssignment, resizeAssignmentDrawer, retractAssignment, retypeMaterial, role, selectedAssignment, statusLabel, submissionBoardPane, submitAssignment, teacherSubmissionSummary, toggleAssignmentDrawerExpanded, uploadMaterialFile, uploadMaterialType } = useShellContext()
</script>

<template>
        <template v-if="role==='TEACHER'">
          <Transition name="drawer-fade" appear><div class="assignment-drawer-mask" @click="closeAssignmentDrawer"></div></Transition>
        </template>
        <Transition :name="role==='TEACHER'?'drawer-slide':'detail-fade'" appear>
        <div :class="{'assignment-detail-drawer':role==='TEACHER','expanded':role==='TEACHER'&&assignmentDrawerExpanded,'resizing':assignmentDrawerResizing}" :style="role==='TEACHER'?{'--drawer-width':`${assignmentDrawerWidth}px`,width:`${assignmentDrawerWidth}px`}:undefined">
         <span v-if="role==='TEACHER'" class="drawer-resize-handle with-center-control drawer-resize-handle-top" role="separator" aria-label="调整作业详情抽屉宽度" aria-orientation="vertical" @pointerdown="resizeAssignmentDrawer"/>
         <span v-if="role==='TEACHER'" class="drawer-resize-handle with-center-control drawer-resize-handle-bottom" role="separator" aria-label="调整作业详情抽屉宽度" aria-orientation="vertical" @pointerdown="resizeAssignmentDrawer"/>
         <a-tooltip v-if="role==='TEACHER'" :open="assignmentDrawerAnimating?false:undefined" :title="assignmentDrawerExpanded?'收回':'展开至全屏'" placement="right"><button type="button" class="assignment-drawer-expand-button" :aria-label="assignmentDrawerExpanded?'收回作业详情':'将作业详情展开至全屏'" @pointerdown.stop @click="toggleAssignmentDrawerExpanded"><RightOutlined v-if="assignmentDrawerExpanded"/><ExpandOutlined v-else/></button></a-tooltip>
         <div class="page-title detail-title"><div><div class="eyebrow">作业详情</div><h1>{{selectedAssignment.title}}</h1><div class="assignment-title-meta"><a-tag :color="selectedAssignment.kind==='EXPERIMENT'?'purple':'blue'">{{assignmentTypeLabel(selectedAssignment)}}</a-tag><a-tag :color="selectedAssignment.status==='PUBLISHED'?'green':'default'">{{statusLabel(selectedAssignment.status)}}</a-tag><span>截止 {{formatTime(selectedAssignment.due_at)}}</span><a-tag v-if="selectedAssignment.allow_late">允许迟交</a-tag></div></div><a-button @click="closeAssignmentDrawer"><ArrowLeftOutlined/> 返回作业列表</a-button></div>
         <section class="assignment-workspace">
           <template v-if="role==='STUDENT'">
             <div class="student-assignment-content">
               <header class="student-workspace-intro">
                 <div><span class="student-workspace-label">作业要求</span><div class="rich-text detail-description" v-html="selectedAssignment.description"></div></div>
                 <div class="student-workspace-state" :class="{submitted:assignmentSubmitted,closed:!canEditAssignment&&!assignmentSubmitted}"><CheckCircleOutlined v-if="assignmentSubmitted"/><InboxOutlined v-else/><div><strong>{{assignmentSubmitted?'已提交':new Date(selectedAssignment.due_at)<=new Date()&&!selectedAssignment.allow_late?'已截止':'在线编写中'}}</strong><span>{{assignmentSubmitted?`${formatTime(selectedAssignment.submission?.submitted_at)} · 可继续修改`:`截止 ${formatTime(selectedAssignment.due_at)}`}}</span></div></div>
               </header>
               <OnlineMarkdownWorkspace ref="onlineWorkspace" :key="selectedAssignment.id" :assignment-id="selectedAssignment.id" :writable="canEditAssignment" :can-submit="canSubmitAssignment&&Boolean(onlineWorkspaceData?.documents?.length)" :submit-label="assignmentIsUpdate?'更新提交':'提交当前版本'" @ready="onlineWorkspaceData=$event" @submit="submitAssignment"/>
               <footer class="student-submit-bar">
                 <span v-if="selectedAssignment.submitter_type==='TEAM'&&!canManageTeamSubmission">小组成员均可协作编辑，由组长正式提交</span>
                 <span v-else>{{onlineWorkspaceData?.documents?.length||0}} 份 Markdown 文档将作为一个版本提交</span>
               </footer>
             </div>
           </template>
           <a-tabs v-else :active-key="assignmentDetailTab" :animated="{inkBar:true,tabPane:true}" class="assignment-detail-tabs" @change="changeAssignmentDetailTab">
            <a-tab-pane key="details" :tab="role==='TEACHER'?'详情':'作业详情'">
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业说明</h2></div>
                <div class="rich-text detail-description" v-html="selectedAssignment.description"></div>
              </section>
              <section class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业资料</h2><a-space><span v-if="assignmentAttachments.length">{{assignmentAttachments.length}} 个附件</span><a-segmented v-if="role==='TEACHER'" v-model:value="uploadMaterialType" size="small" :options="materialTypeOptions"/><a-upload v-if="role==='TEACHER'" :custom-request="uploadMaterialFile" :show-upload-list="false" :accept="uploadMaterialType==='CRITERIA'?'.md':undefined" multiple><a-button><UploadOutlined/> 上传作业附件</a-button></a-upload></a-space></div>
                <a-empty v-if="!assignmentAttachments.length" class="detail-empty" description="暂无作业资料"/>
                <AssignmentMaterials v-else :files="assignmentAttachments" :assignment-id="selectedAssignment.id" :can-delete="role==='TEACHER'" can-download :deleting="deletingMaterials" @preview="openFilePreview" @delete="deleteDraft" @delete-selected="deleteSelectedMaterials" @retype="retypeMaterial"/>
              </section>
              <section v-if="role==='TEACHER'" class="assignment-pane">
                <div class="assignment-pane-heading"><h2>作业操作</h2></div>
                <a-space wrap><a-button @click="openAssignmentEdit"><EditOutlined/> 编辑作业</a-button><a-button v-if="selectedAssignment.status==='DRAFT'" type="primary" @click="publishAssignment">发布作业</a-button><a-button v-if="selectedAssignment.status==='PUBLISHED'&&new Date(selectedAssignment.due_at)>new Date()" danger @click="closeAssignment">提前截止</a-button><a-button v-if="['PUBLISHED','CLOSED'].includes(selectedAssignment.status)" danger @click="retractAssignment">撤回发布</a-button><a-button danger @click="deleteAssignment"><DeleteOutlined/> 删除作业</a-button></a-space>
              </section>
            </a-tab-pane>
            <a-tab-pane key="submission" :tab="role==='TEACHER'?'提交情况':'提交作业'">
              <template v-if="role==='TEACHER'">
                <section class="assignment-pane teacher-submission-pane">
                  <div class="assignment-pane-heading"><h2>提交概览</h2><a-space wrap><a-button :loading="exportingAssignment" @click="downloadAssignmentSubmissions"><DownloadOutlined/> 下载全部学生作业</a-button><a-button v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" :href="`/api/v1/exports/grades.xlsx?class_id=${classId}&assignment_id=${selectedAssignment.id}`"><DownloadOutlined/> 导出所有学生成绩</a-button></a-space></div>
                  <div class="detail-metrics"><div class="detail-metric" role="button" tabindex="0" aria-label="查看全部应提交记录" @click="focusSubmissionStatus('ALL')" @keydown.enter.prevent="focusSubmissionStatus('ALL')" @keydown.space.prevent="focusSubmissionStatus('ALL')"><span>应提交</span><strong>{{teacherSubmissionSummary.total}}</strong></div><div class="detail-metric" role="button" tabindex="0" aria-label="查看已提交记录" @click="focusSubmissionStatus('SUBMITTED')" @keydown.enter.prevent="focusSubmissionStatus('SUBMITTED')" @keydown.space.prevent="focusSubmissionStatus('SUBMITTED')"><span>已提交</span><strong>{{teacherSubmissionSummary.submitted}}</strong></div><div class="detail-metric" role="button" tabindex="0" aria-label="查看未提交记录" @click="focusSubmissionStatus('NOT_SUBMITTED')" @keydown.enter.prevent="focusSubmissionStatus('NOT_SUBMITTED')" @keydown.space.prevent="focusSubmissionStatus('NOT_SUBMITTED')"><span>未提交</span><strong>{{teacherSubmissionSummary.pending}}</strong></div><div class="detail-metric" role="button" tabindex="0" aria-label="查看迟交记录" @click="focusSubmissionStatus('LATE')" @keydown.enter.prevent="focusSubmissionStatus('LATE')" @keydown.space.prevent="focusSubmissionStatus('LATE')"><span>迟交</span><strong>{{teacherSubmissionSummary.late}}</strong></div></div>
                </section>
                <section class="assignment-pane">
                  <div ref="submissionBoardPane">
                  <div class="assignment-pane-heading"><h2>提交明细</h2></div>
                  <div class="board-toolbar"><a-input-search v-model:value="boardQuery" allow-clear placeholder="搜索姓名或学号"/><a-select v-model:value="boardTeamFilter" :options="boardTeamOptions"/><a-segmented v-model:value="boardFilter" :options="[{label:'全部',value:'ALL'},{label:'未提交',value:'NOT_SUBMITTED'},{label:'已提交',value:'SUBMITTED'},{label:'迟交',value:'LATE'},{label:'未批改',value:'PENDING_REVIEW'},{label:'已批改',value:'REVIEWED'}]"/></div>
                  <a-empty v-if="!groupedBoard.length" class="detail-empty" description="没有符合条件的提交记录"/>
                  <section v-for="group in groupedBoard" :key="group.id" class="submission-group"><div class="submission-group-heading"><strong>{{group.name}}</strong><span>{{group.items.length}} 人</span></div><a-table :data-source="group.items" row-key="id" size="small" :pagination="false"><a-table-column title="提交对象" data-index="owner"/><a-table-column v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" title="学号"><template #default="{record}">{{record.student_no||'-'}}</template></a-table-column><a-table-column title="状态"><template #default="{record}"><a-tag>{{statusLabel(record.status)}}</a-tag><a-tag v-if="record.is_late" color="red">迟交</a-tag></template></a-table-column><a-table-column v-if="selectedAssignment.submitter_type==='INDIVIDUAL'" title="互评"><template #default="{record}">{{record.peer_grade||'-'}}<small v-if="record.peer_review_count">（{{record.peer_review_count}} 人）</small></template></a-table-column><a-table-column title="最终成绩"><template #default="{record}"><span v-if="record.final_grade" class="grade-result" :class="`source-${(record.grade_source||'unknown').toLowerCase()}`"><strong>{{record.final_grade}}</strong><span>{{gradeSourceLabel(record.grade_source)}}</span></span><a-tag v-else :color="gradingStatusColor(record.grading_status)">{{statusLabel(record.grading_status)}}</a-tag><a-tag v-if="record.grade_carried_forward" color="blue">待重新评分</a-tag></template></a-table-column><a-table-column title="提交时间"><template #default="{record}">{{formatTime(record.submitted_at)}}</template></a-table-column><a-table-column title="操作" :width="110"><template #default="{record}"><a-button v-if="record.status==='SUBMITTED'" type="link" @click="openSubmissionDetail(record)"><EyeOutlined/> 查看作业</a-button><span v-else>-</span></template></a-table-column></a-table></section>
                  </div>
                </section>
              </template>
              <template v-else>
              <div class="submission-summary" :class="{submitted:assignmentSubmitted,closed:!canEditAssignment&&!assignmentSubmitted}"><span class="submission-summary-icon"><CheckCircleOutlined v-if="assignmentSubmitted"/><InboxOutlined v-else/></span><div><strong>{{assignmentSubmitted?'已提交':new Date(selectedAssignment.due_at)<=new Date()&&!selectedAssignment.allow_late?'已截止':'在线编写中'}}</strong><span>{{assignmentSubmitted?`${formatTime(selectedAssignment.submission?.submitted_at)} · 可继续编辑并更新提交`:`截止 ${formatTime(selectedAssignment.due_at)}`}}</span></div></div>
              <section class="assignment-pane online-workspace-pane">
                <OnlineMarkdownWorkspace ref="onlineWorkspace" :key="selectedAssignment.id" :assignment-id="selectedAssignment.id" :writable="canEditAssignment" :can-submit="canSubmitAssignment&&Boolean(onlineWorkspaceData?.documents?.length)" :submit-label="assignmentIsUpdate?'更新提交':'提交当前版本'" @ready="onlineWorkspaceData=$event" @submit="submitAssignment"/>
                <a-alert v-if="selectedAssignment.submitter_type==='TEAM'&&canEditAssignment" type="info" show-icon message="小组成员均可协作编辑，由组长正式提交"/>
              </section>
              </template>
            </a-tab-pane>
          </a-tabs>
        </section>
        </div>
        </Transition>
</template>
