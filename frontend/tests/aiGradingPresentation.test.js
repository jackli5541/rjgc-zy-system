import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

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
})
