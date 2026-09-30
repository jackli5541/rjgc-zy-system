import assert from 'node:assert/strict'
import test from 'node:test'
import { beijingDateTimeToIso, formatBeijingTime, toBeijingDateTimeLocal } from '../src/shared/time.js'

test('timestamps display in Beijing time regardless of browser timezone', () => {
  for (const value of ['2026-09-29T05:48:05Z', '2026-09-29T05:48:05', '2026-09-29T13:48:05+08:00']) {
    assert.equal(formatBeijingTime(value), '2026/09/29 13:48:05')
    assert.equal(toBeijingDateTimeLocal(value), '2026-09-29T13:48')
  }
  assert.equal(formatBeijingTime('2026-09-29T20:00:00Z'), '2026/09/30 04:00:00')
})

test('Beijing form values round trip without a timezone shift', () => {
  const iso = beijingDateTimeToIso('2026-09-30T00:15')
  assert.equal(iso, '2026-09-29T16:15:00.000Z')
  assert.equal(toBeijingDateTimeLocal(iso), '2026-09-30T00:15')
  assert.equal(beijingDateTimeToIso(''), null)
  assert.equal(formatBeijingTime('invalid'), '-')
})
