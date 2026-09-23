<script setup>
import AssignmentMaterials from './AssignmentMaterials.vue'
import { BoldOutlined, CodeOutlined, LinkOutlined, OrderedListOutlined, UnorderedListOutlined, UploadOutlined } from '@ant-design/icons-vue'
import { EditorContent } from '@tiptap/vue-3'
import { useShellContext } from '../../../shellContext'

const { assignmentAttachments, assignmentForm, classOptions, createAssignment, deleteDraft, deleteSelectedMaterials, deletingMaterials, descriptionEditor, materialTypeOption, materialTypeOptions, modals, openFilePreview, pendingAssignmentFiles, queueAssignmentAttachment, removePendingAssignmentAttachment, setDescriptionLink } = useShellContext()
</script>

<template>
    <a-modal v-model:open="modals.assignment" :title="assignmentForm.id ? '编辑作业' : '新建作业'" :footer="null" width="720px">
      <a-form layout="vertical">
        <a-form-item label="教学班" required><a-select v-model:value="assignmentForm.class_ids" mode="multiple" placeholder="选择一个或多个教学班" :options="classOptions"/></a-form-item>
        <a-form-item label="标题" required><a-input v-model:value="assignmentForm.title"/></a-form-item>
        <a-form-item label="类型"><a-segmented v-model:value="assignmentForm.kind" :options="[{label:'作业',value:'ASSIGNMENT'},{label:'实验',value:'EXPERIMENT'}]"/></a-form-item>
        <a-form-item label="提交类型" :help="assignmentForm.has_submissions ? '已有提交，不能修改提交类型' : ''"><a-segmented v-model:value="assignmentForm.submitter_type" :disabled="assignmentForm.has_submissions||assignmentForm.auto_review_enabled" :options="[{label:'个人作业',value:'INDIVIDUAL'},{label:'小组作业',value:'TEAM'}]"/></a-form-item>
        <a-form-item label="开始时间"><a-input v-model:value="assignmentForm.starts_at" type="datetime-local"/></a-form-item>
        <a-form-item label="截止时间" required><a-input v-model:value="assignmentForm.due_at" type="datetime-local"/></a-form-item>
        <a-form-item label="说明" required><div class="editor-shell"><div v-if="descriptionEditor" class="editor-toolbar"><a-tooltip title="二级标题"><a-button size="small" :type="descriptionEditor.isActive('heading',{level:2})?'primary':'default'" @click="descriptionEditor.chain().focus().toggleHeading({level:2}).run()">H2</a-button></a-tooltip><a-tooltip title="粗体"><a-button size="small" :type="descriptionEditor.isActive('bold')?'primary':'default'" @click="descriptionEditor.chain().focus().toggleBold().run()"><BoldOutlined/></a-button></a-tooltip><a-tooltip title="无序列表"><a-button size="small" @click="descriptionEditor.chain().focus().toggleBulletList().run()"><UnorderedListOutlined/></a-button></a-tooltip><a-tooltip title="有序列表"><a-button size="small" @click="descriptionEditor.chain().focus().toggleOrderedList().run()"><OrderedListOutlined/></a-button></a-tooltip><a-tooltip title="链接"><a-button size="small" @click="setDescriptionLink"><LinkOutlined/></a-button></a-tooltip><a-tooltip title="代码块"><a-button size="small" @click="descriptionEditor.chain().focus().toggleCodeBlock().run()"><CodeOutlined/></a-button></a-tooltip></div><EditorContent :editor="descriptionEditor"/></div></a-form-item>
        <a-form-item label="作业资料">
          <AssignmentMaterials v-if="assignmentForm.id&&assignmentAttachments.length" :files="assignmentAttachments" can-delete can-download :deleting="deletingMaterials" @preview="openFilePreview" @delete="deleteDraft" @delete-selected="deleteSelectedMaterials"/>
          <div class="assignment-material-upload-actions">
            <a-upload v-for="option in materialTypeOptions" :key="option.value" :before-upload="file => queueAssignmentAttachment(file, option.value)" :show-upload-list="false" multiple accept=".md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.pptx,.xlsx,.zip,.rar,.7z">
              <a-button><UploadOutlined/> 选择{{option.value==='ATTACHMENT'?'附件':option.label}}</a-button>
            </a-upload>
          </div>
          <div v-for="(pending,index) in pendingAssignmentFiles" :key="pending.file.uid||`${pending.file.name}-${index}`" class="uploaded-file assignment-material-pending">
            <span class="assignment-material-pending-name">{{pending.file.name}}</span>
            <a-tag :color="materialTypeOption(pending.materialType).color">{{materialTypeOption(pending.materialType).label}}</a-tag>
            <a-button danger type="link" @click="removePendingAssignmentAttachment(index)">移除</a-button>
          </div>
        </a-form-item>
        <a-checkbox v-model:checked="assignmentForm.allow_late">允许迟交并标记</a-checkbox>
        <div class="modal-actions"><a-button @click="modals.assignment=false">取消</a-button><a-button @click="createAssignment(false)">{{assignmentForm.id?'保存修改':'保存草稿'}}</a-button><a-button type="primary" @click="createAssignment(true)">{{assignmentForm.id?'保存并再次发布':'发布'}}</a-button></div>
      </a-form>
    </a-modal>
</template>
