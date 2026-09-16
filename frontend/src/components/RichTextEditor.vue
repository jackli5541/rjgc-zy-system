<script setup>
import { onBeforeUnmount, watch } from 'vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import { BoldOutlined, CodeOutlined, LinkOutlined, OrderedListOutlined, UnorderedListOutlined } from '@ant-design/icons-vue'

const props = defineProps({ modelValue: { type: String, default: '' }, placeholder: { type: String, default: '' }, compact: Boolean, autofocus: Boolean })
const emit = defineEmits(['update:modelValue'])
const editor = useEditor({
  content: props.modelValue,
  extensions: [StarterKit.configure({ link: { openOnClick: false } })],
  editorProps: { attributes: { 'data-placeholder': props.placeholder } },
  onCreate: ({ editor: instance }) => { if (props.autofocus) instance.commands.focus('end') },
  onUpdate: ({ editor: instance }) => emit('update:modelValue', instance.getHTML())
})

watch(() => props.modelValue, value => {
  if (editor.value && editor.value.getHTML() !== value) editor.value.commands.setContent(value || '', { emitUpdate: false })
})
onBeforeUnmount(() => editor.value?.destroy())

function setLink() {
  const previous = editor.value?.getAttributes('link').href || ''
  const href = window.prompt('输入 HTTPS 链接', previous)
  if (href === null) return
  if (!href) editor.value.chain().focus().unsetLink().run()
  else if (/^https:\/\//i.test(href)) editor.value.chain().focus().extendMarkRange('link').setLink({ href }).run()
}
</script>

<template>
  <div class="feedback-rich-editor" :class="{compact}">
    <div v-if="editor" class="feedback-editor-toolbar">
      <a-tooltip title="粗体"><a-button size="small" :type="editor.isActive('bold')?'primary':'default'" @click="editor.chain().focus().toggleBold().run()"><BoldOutlined/></a-button></a-tooltip>
      <a-tooltip title="无序列表"><a-button size="small" @click="editor.chain().focus().toggleBulletList().run()"><UnorderedListOutlined/></a-button></a-tooltip>
      <a-tooltip title="有序列表"><a-button size="small" @click="editor.chain().focus().toggleOrderedList().run()"><OrderedListOutlined/></a-button></a-tooltip>
      <a-tooltip title="链接"><a-button size="small" @click="setLink"><LinkOutlined/></a-button></a-tooltip>
      <a-tooltip title="代码块"><a-button size="small" @click="editor.chain().focus().toggleCodeBlock().run()"><CodeOutlined/></a-button></a-tooltip>
    </div>
    <EditorContent :editor="editor"/>
  </div>
</template>

<style scoped>
.feedback-rich-editor{overflow:hidden;border:1px solid #d5dde5;border-radius:6px;background:#fff}.feedback-editor-toolbar{display:flex;gap:4px;padding:6px;border-bottom:1px solid #e7ecf1;background:#f7f9fb}.feedback-rich-editor :deep(.tiptap){min-height:104px;padding:10px 12px;outline:none;line-height:1.55}.feedback-rich-editor.compact :deep(.tiptap){min-height:76px}.feedback-rich-editor :deep(.tiptap p){margin:0 0 7px}.feedback-rich-editor :deep(.tiptap p:last-child){margin-bottom:0}.feedback-rich-editor :deep(.tiptap:empty:before){float:left;color:#a7b0ba;content:attr(data-placeholder);pointer-events:none}
</style>
