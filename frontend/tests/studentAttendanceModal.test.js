import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { computed, effectScope, nextTick, ref, watch } from 'vue'

test('opening the lazily mounted student modal loads attendance and starts refresh immediately', async () => {
  const source = readFileSync(new URL('../src/modules/attendance/components/StudentAttendanceModal.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const attendanceOpen = ref(true)
  const classId = ref('class-1')
  const requests = []
  const intervals = new Map()
  const cleanup = []
  const scope = effectScope()
  const active = { id: 'session-1', title: '课堂签到', record: { status: 'PENDING' } }
  const setup = new Function('computed', 'ref', 'watch', 'onBeforeUnmount', 'useShellContext', 'api', 'message', 'setInterval', 'clearInterval', `${script}\nreturn { data }`)
  try {
    const state = scope.run(() => setup(
      computed, ref, watch, callback => cleanup.push(callback),
      () => ({ attendanceOpen, classId }),
      async path => { requests.push(path); return { active, recent: [] } },
      { error: error => assert.fail(error) },
      (callback, delay) => { intervals.set(1, { callback, delay }); return 1 },
      id => intervals.delete(id),
    ))
    await nextTick()
    assert.deepEqual(requests, ['/classes/class-1/attendance/current'])
    assert.equal(state.data.value.active.id, active.id)
    assert.equal(intervals.get(1).delay, 10000)
    await intervals.get(1).callback()
    assert.equal(requests.length, 2)
    classId.value = 'class-2'
    await nextTick()
    assert.equal(requests.at(-1), '/classes/class-2/attendance/current')
    cleanup.forEach(callback => callback())
    assert.equal(intervals.size, 0)
  } finally {
    scope.stop()
  }
})
