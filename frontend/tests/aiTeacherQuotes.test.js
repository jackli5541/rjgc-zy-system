import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'

function componentStatements(name, select) {
  const source = readFileSync(new URL(`../src/modules/assignments/components/${name}.vue`, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: name })
  return script.scriptSetupAst.filter(select).map(node => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n')
}

test('removed quotes stay removed when another region is added, including after removing all quotes', () => {
  const state = vm.createContext({
    aiTeacherQuotes: { value: [] }, aiTeacherQuote: { value: '' },
    aiTeacherQuoteSource: { value: null }, aiTeacherQuoteVersion: { value: 0 },
    aiTeacherOpen: { value: true }, selectedQuotes: { value: [] }
  })
  vm.runInContext(componentStatements('AssignmentDetailDrawer', node => node.type === 'FunctionDeclaration' && ['updateAiTeacherQuotes', 'openAiTeacher'].includes(node.id.name)), state)
  state.props = {}
  state.watch = (_, callback) => { state.syncQuotes = callback }
  state.emit = (event, quotes) => {
    if (event === 'update-quotes') state.updateAiTeacherQuotes(quotes)
  }
  vm.runInContext(componentStatements('AiTeacherDrawer', node =>
    node.type === 'FunctionDeclaration' && node.id.name === 'removeQuote' ||
    node.type === 'ExpressionStatement' && node.expression.type === 'CallExpression' &&
      node.expression.callee.name === 'watch' &&
      node.expression.arguments[0]?.body?.property?.name === 'quoteVersion'
  ), state)
  const add = quote => {
    state.openAiTeacher(quote, 'assignment')
    Object.assign(state.props, { quotes: state.aiTeacherQuotes.value, quote: state.aiTeacherQuote.value, quoteSource: state.aiTeacherQuoteSource.value })
    state.syncQuotes()
  }
  const contents = () => Array.from(state.selectedQuotes.value, item => item.quote)
  add('region A')
  add('region B')
  state.removeQuote(0)
  add('region C')
  assert.deepEqual(contents(), ['region B', 'region C'])
  state.removeQuote(1)
  state.removeQuote(0)
  assert.equal(state.aiTeacherQuote.value, '')
  assert.equal(state.aiTeacherQuoteSource.value, null)
  add('region D')
  assert.deepEqual(contents(), ['region D'])
  add('region A')
  assert.deepEqual(contents(), ['region D', 'region A'])
  // Selecting text alone does not call the explicit quote action. Reopening
  // through the ordinary entry must also clear the drawer's previous quotes.
  state.aiTeacherOpen.value = false
  add('')
  assert.deepEqual(contents(), [])
  add('explicit new quote')
  assert.deepEqual(contents(), ['explicit new quote'])
})

test('editor toolbar opens chat without quoting a retained editor selection', () => {
  const source = readFileSync(new URL('../src/shared/components/RichTextEditor.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'RichTextEditor' })
  const calls = []
  const state = vm.createContext({
    askAiTeacher: (...args) => calls.push(args),
    selectedText: () => 'selected but not explicitly quoted',
    selectionAction: { value: {} }
  })
  const functions = script.scriptSetupAst.filter(node => node.type === 'FunctionDeclaration' && ['askAi', 'openAiChat'].includes(node.id.name))
  vm.runInContext(functions.map(node => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n'), state)
  state.openAiChat()
  assert.deepEqual(calls, [[]])
  state.askAi()
  assert.deepEqual(calls[1], ['selected but not explicitly quoted'])
  assert.match(descriptor.template.content, /@click="openAiChat"/)
  assert.match(descriptor.template.content, /@ask="askAi"/)
})
