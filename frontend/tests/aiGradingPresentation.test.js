import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import vm from 'node:vm'

test('concise grading panel exposes one adoption action and collapses evidence', () => {
  const source = readFileSync(new URL('../src/modules/ai_grading/components/SingleAiGradingPanel.vue', import.meta.url), 'utf8')
  const { descriptor, errors } = parse(source)
  assert.deepEqual(errors, [])
  compileScript(descriptor, { id: 'grading' })
  const result = compileTemplate({ source: descriptor.template.content, filename: 'SingleAiGradingPanel.vue', id: 'grading' })
  assert.deepEqual(result.errors, [])
  const template = descriptor.template.content
  const adoption = [...template.matchAll(/<a-button[^>]+@click="adopt"[^>]*>/g)]
  assert.equal(adoption.length, 1)
  assert.match(adoption[0][0], /:disabled="disabled \|\| adopted"/)
  assert.match(template, /已采用/)
  assert.match(template, /显示全部/)
  assert.match(template, /<details><summary>查看判定明细<\/summary>/)
  assert.doesNotMatch(template, /<details[^>]*\bopen\b/)
  assert.match(template, /draft.grade_changed/)
  assert.match(template, /draft.materials_changed/)
  assert.match(template, /查看上次成功建议/)
  assert.match(template, /上次 AI 建议/)
  assert.match(template, /本次 AI 建议/)
  assert.match(template, /上次 AI 定级理由/)
})

test('AI grading follows student annotations in the review sidebar', () => {
  const source = readFileSync(new URL('../src/modules/assignments/components/FileReviewDrawer.vue', import.meta.url), 'utf8')
  const { descriptor, errors } = parse(source)
  assert.deepEqual(errors, [])
  const template = descriptor.template.content
  const studentAnnotations = template.indexOf('class="peer-annotation-list"')
  const aiPanel = template.indexOf('<SingleAiGradingPanel')
  const feedbackActions = template.indexOf('class="feedback-actions"')
  assert.ok(studentAnnotations >= 0 && aiPanel > studentAnnotations && feedbackActions > aiPanel)
  assert.equal([...template.matchAll(/<SingleAiGradingPanel\b/g)].length, 1)
})

test('AI grading is restricted to the current teacher in editable teacher review mode', () => {
  const source = readFileSync(new URL('../src/modules/assignments/components/FileReviewDrawer.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'role-guard' })
  const declaration = script.scriptSetupAst.flatMap(node => node.declarations || []).find(node => node.id?.name === 'aiEnabled')
  const expression = descriptor.scriptSetup.content.slice(declaration.init.arguments[0].start, declaration.init.arguments[0].end)
  const enabled = props => vm.runInNewContext(`(${expression})()`, { props })
  const teacher = { open: true, editable: true, viewerRole: 'TEACHER', mode: 'TEACHER' }
  assert.equal(enabled(teacher), true)
  for (const mode of ['TEACHER', 'PEER', 'READONLY']) {
    assert.equal(enabled({ ...teacher, viewerRole: 'STUDENT', mode }), false)
  }
  assert.equal(enabled({ ...teacher, viewerRole: '' }), false)
  assert.equal(enabled({ ...teacher, mode: 'PEER' }), false)
  assert.equal(enabled({ ...teacher, editable: false }), false)
  assert.equal(enabled({ ...teacher, open: false }), false)
  assert.match(descriptor.template.content, /<SingleAiGradingPanel v-if="aiEnabled"/)
  assert.match(descriptor.template.content, /<a-button v-if="aiEnabled"[^>]*@click="startAiGrading"/)
  assert.match(source, /useSingleAiGrading\(\(\) => aiEnabled\.value/)
  assert.match(source, /watch\(\(\) => \[props\.open, props\.mode, props\.viewerRole, props\.editable,/)
  const parent = readFileSync(new URL('../src/modules/assignments/components/AssignmentReviewDrawer.vue', import.meta.url), 'utf8')
  assert.match(parent, /:viewer-role="role"/)
})
