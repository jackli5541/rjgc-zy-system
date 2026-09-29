const configuredName = import.meta.env.VITE_AI_TEACHER_NAME?.trim()
const configuredActionLabel = import.meta.env.VITE_AI_TEACHER_ACTION_LABEL?.trim()
const configuredAvatarUrl = import.meta.env.VITE_AI_TEACHER_AVATAR_URL?.trim()

export const aiTeacherName = configuredName || '叶老师'
export const aiTeacherActionLabel = configuredActionLabel || `问问${aiTeacherName}`
export const aiTeacherAvatarUrl = configuredAvatarUrl || '/teacher.jpg'
