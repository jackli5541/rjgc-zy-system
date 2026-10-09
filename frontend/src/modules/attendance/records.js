export function recentCheckedInRecords(records = []) {
  const timestamp = record => Date.parse(record.checked_in_at) || 0
  return records.filter(record => ['PRESENT', 'LATE'].includes(record.status))
    .sort((first, second) => timestamp(second) - timestamp(first))
}

export function filterAttendanceRecords(records = [], keyword = '', status = '') {
  const search = keyword.trim().toLowerCase()
  return records.filter(record => (!status || record.status === status)
    && (!search || [record.student_name, record.student_no].some(value => String(value ?? '').toLowerCase().includes(search))))
}
