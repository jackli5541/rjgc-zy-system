import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, nextTick, ref } from 'vue'
import { useProjectionFeedback } from '../src/modules/attendance/composables/useProjectionFeedback.js'

const record = (studentId, status = 'PRESENT') => ({ student_id: studentId, student_name: `同学${studentId}`, status, checked_in_at: '2026-10-09T01:00:00Z' })

test('projection ignores history and refreshes, batches arrivals, and resets on reopening', async () => {
  const scope = effectScope()
  const selected = ref({ id: 1, status: 'ACTIVE', total: 10, records: [record(1)] })
  const projecting = ref(false)
  const feedback = scope.run(() => useProjectionFeedback(selected, projecting))
  try {
    projecting.value = true
    await nextTick()
    assert.equal(feedback.newcomers.value.length, 0)
    selected.value.records.push(record(2, 'LATE'))
    await nextTick()
    assert.equal(feedback.feedbackText.value, '同学2 已签到 · 迟到')
    assert.ok(feedback.highlightedIds.value.has(2))
    const key = feedback.feedbackKey.value
    selected.value = structuredClone({ ...selected.value, records: selected.value.records.map(item => ({ ...item, note: '备注' })) })
    await nextTick()
    assert.equal(feedback.feedbackKey.value, key)
    selected.value.records.push(...[3, 4, 5, 6].map(studentId => record(studentId)))
    await nextTick()
    assert.equal(feedback.feedbackText.value, '新增 4 人签到')
    projecting.value = false
    await nextTick()
    assert.equal(feedback.newcomers.value.length, 0)
    projecting.value = true
    await nextTick()
    assert.equal(feedback.newcomers.value.length, 0)
    selected.value = { id: 2, status: 'ACTIVE', total: 2, records: [record(7)] }
    await nextTick()
    assert.equal(feedback.newcomers.value.length, 0)
    selected.value.records.push(record(8))
    await nextTick()
    assert.equal(feedback.feedbackText.value, '全员签到完成！')
    assert.equal(feedback.completed.value, true)
    const completionKey = feedback.feedbackKey.value
    selected.value = { ...selected.value, code: '123456' }
    await nextTick()
    assert.equal(feedback.feedbackKey.value, completionKey)
    projecting.value = false
    await nextTick()
    projecting.value = true
    await nextTick()
    assert.equal(feedback.completed.value, false)
    assert.equal(feedback.newcomers.value.length, 0)
  } finally {
    scope.stop()
  }
})
