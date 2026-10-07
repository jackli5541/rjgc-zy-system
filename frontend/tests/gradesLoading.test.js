import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { ref } from 'vue'

test('grade requests start together, render independently, and discard outdated results', async () => {
  const requests = []
  globalThis.gradeTestApi = path => new Promise(resolve => requests.push({ path, resolve }))
  try {
    const source = (await readFile(new URL('../src/modules/grades/composables/useGrades.js', import.meta.url), 'utf8'))
      .replace("import { api } from '../../../api'", 'const api = globalThis.gradeTestApi')
      .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    const { useGrades } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
    const ctx = { role: ref('TEACHER'), classId: ref('first'), pageKey: ref('first:grades'), loadedViewKeys: new Set() }
    const state = useGrades(ctx)
    let firstCurrent = true
    const first = state.loadGradesView(() => firstCurrent)
    assert.equal(requests.length, 2)
    assert.ok(requests[0].path.includes('/grades/assignments'))
    assert.ok(requests[1].path.includes('/grade-overview'))
    assert.ok(ctx.loadedViewKeys.has('first:grades'))
    requests[1].resolve({ items: [{ student_id: 'first' }] })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(state.overviewItems.value[0].student_id, 'first')
    assert.equal(state.overviewLoading.value, false)
    assert.equal(state.gradeAssignmentsLoading.value, true)

    firstCurrent = false
    ctx.classId.value = 'second'
    ctx.pageKey.value = 'second:grades'
    const second = state.loadGradesView(() => true)
    assert.deepEqual(state.overviewItems.value, [])
    requests[0].resolve({ items: [{ id: 'outdated' }] })
    await first
    assert.deepEqual(state.gradeAssignments.value, [])
    assert.equal(state.gradeAssignmentsLoading.value, true)
    requests[2].resolve({ items: [{ id: 'second' }] })
    requests[3].resolve({ items: [{ student_id: 'second' }] })
    await second
    assert.equal(state.gradeAssignments.value[0].id, 'second')
    assert.equal(state.overviewItems.value[0].student_id, 'second')
    assert.equal(state.gradeAssignmentsLoading.value, false)
    assert.equal(state.overviewLoading.value, false)
  } finally {
    delete globalThis.gradeTestApi
  }
})
