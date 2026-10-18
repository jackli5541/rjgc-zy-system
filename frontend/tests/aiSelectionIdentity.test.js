import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'

function functions(path, names) {
  const { descriptor } = parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
  return compileScript(descriptor, { id: 'selection-identity' }).scriptSetupAst
    .filter(node => node.type === 'FunctionDeclaration' && names.includes(node.id.name))
    .map(node => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n')
}

test('editor keeps one action for repeated selection events and quotes the current selection', () => {
  let top = 240
  let quote
  const state = {
    props: { document: true }, selectionAction: { value: null }, aiTeacherDocumentId: { value: 'document-A' },
    editor: { value: { state: { selection: { from: 2, to: 8, empty: false }, doc: { textBetween: () => 'selected words' } } } },
    askAiTeacher: text => { quote = text },
    window: { innerWidth: 1200, getSelection: () => ({ rangeCount: 1, getRangeAt: () => ({ cloneRange: () => ({ getBoundingClientRect: () => ({ width: 100, left: 600, top }) }) }) }) }
  }
  const context = vm.createContext(state)
  vm.runInContext(functions('../src/shared/components/RichTextEditor.vue', ['selectedText', 'updateSelectionAction', 'askAi']), context)
  context.updateSelectionAction()
  const original = state.selectionAction.value
  top = 500
  context.updateSelectionAction()
  assert.equal(state.selectionAction.value, original)
  state.editor.value.state.selection.to = 12
  context.updateSelectionAction()
  assert.notEqual(state.selectionAction.value.selectionId, original.selectionId)
  const oldId = state.selectionAction.value.selectionId
  state.aiTeacherDocumentId.value = 'document-B'
  context.updateSelectionAction()
  assert.notEqual(state.selectionAction.value.selectionId, oldId)
  context.askAi()
  assert.equal(quote, 'selected words')
  assert.equal(state.selectionAction.value, null)
  context.updateSelectionAction()
  state.editor.value.state.selection.empty = true
  context.updateSelectionAction()
  assert.equal(state.selectionAction.value, null)
})

test('requirement selection identity uses DOM boundaries rather than geometry or text alone', () => {
  let top = 200
  const node = {}
  const range = {
    startContainer: node, startOffset: 0, endContainer: node, endOffset: 10, commonAncestorContainer: node,
    getBoundingClientRect: () => ({ left: 600, top }), cloneRange() { return { ...this } }
  }
  const state = {
    role: { value: 'STUDENT' }, selectedAssignment: { value: { id: 'assignment-A' } },
    requirementSelection: { value: null }, requirementRange: null, requirementSelectionVersion: 0,
    window: { innerWidth: 1200, getSelection: () => ({ toString: () => 'same text', rangeCount: 1, getRangeAt: () => range }) }
  }
  const context = vm.createContext(state)
  vm.runInContext(functions('../src/modules/assignments/components/AssignmentDetailDrawer.vue', ['selectRequirement']), context)
  const event = { currentTarget: { contains: () => true } }
  context.selectRequirement(event)
  const original = state.requirementSelection.value
  top = 450
  context.selectRequirement(event)
  assert.equal(state.requirementSelection.value, original)
  range.startOffset = 1
  context.selectRequirement(event)
  assert.notEqual(state.requirementSelection.value.selectionId, original.selectionId)
  context.selectRequirement({ currentTarget: { contains: () => false } })
  assert.equal(state.requirementSelection.value, null)
})
