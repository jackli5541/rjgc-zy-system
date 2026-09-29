const BEIJING_TIME_ZONE = 'Asia/Shanghai'

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: BEIJING_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23'
})

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: BEIJING_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit'
})

function validDate(value) {
  let normalized = value
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value)) {
    normalized = `${value}Z`
  }
  const date = value instanceof Date ? value : new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatBeijingTime(value, fallback = '-') {
  const date = validDate(value)
  return date ? dateTimeFormatter.format(date) : fallback
}

export function formatBeijingDate(value, fallback = '-') {
  const date = validDate(value)
  return date ? dateFormatter.format(date) : fallback
}

export function toBeijingDateTimeLocal(value) {
  const date = validDate(value)
  if (!date) return ''
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: BEIJING_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(date).filter(part => part.type !== 'literal').map(part => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

export function beijingDateTimeToIso(value) {
  if (!value) return null
  const seconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) ? ':00' : ''
  return new Date(`${value}${seconds}+08:00`).toISOString()
}
