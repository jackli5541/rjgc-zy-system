import assert from 'node:assert/strict'
import test from 'node:test'
import { filterAttendanceRecords, recentCheckedInRecords } from '../src/modules/attendance/records.js'

const records = [
  { student_id: 1, student_name: '张三', student_no: 'S001', status: 'PRESENT', checked_in_at: '2026-10-09T01:00:00Z' },
  { student_id: 2, student_name: '李四', student_no: 'S002', status: 'PENDING', checked_in_at: null },
  { student_id: 3, student_name: '张五', student_no: 'S003', status: 'LATE', checked_in_at: '2026-10-09T01:05:00Z' },
]

test('latest check-ins first without changing the source roster', () => {
  assert.deepEqual(recentCheckedInRecords(records).map(record => record.student_id), [3, 1])
  assert.deepEqual(records.map(record => record.student_id), [1, 2, 3])
  assert.deepEqual(recentCheckedInRecords(), [])
})

test('name, student number and status filters can be combined and cleared', () => {
  assert.equal(filterAttendanceRecords(records).length, 3)
  assert.deepEqual(filterAttendanceRecords(records, ' 张 ').map(record => record.student_id), [1, 3])
  assert.deepEqual(filterAttendanceRecords(records, 's002').map(record => record.student_id), [2])
  assert.deepEqual(filterAttendanceRecords(records, '', 'PENDING').map(record => record.student_id), [2])
  assert.deepEqual(filterAttendanceRecords(records, '张', 'LATE').map(record => record.student_id), [3])
  assert.deepEqual(filterAttendanceRecords(records, '李', 'PRESENT'), [])
  assert.deepEqual(filterAttendanceRecords(), [])
})
