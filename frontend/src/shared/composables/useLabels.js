import { randomUUID } from '../../api'
import { ref } from 'vue'

export function useLabels(ctx) {
  const currentTime = ref(Date.now())

  function iso(value) { return value ? new Date(value).toISOString() : null }

  function idempotencyKey() { return randomUUID() }

  function localDateTime(value) { if (!value) return ''; const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }

  function formatTime(value) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-' }

  function assignmentCountdown(item) {
    const start = item.starts_at ? new Date(item.starts_at).getTime() : 0
    const due = new Date(item.due_at).getTime()
    if (item.status === 'CLOSED' || due <= currentTime.value) return { label: '已结束', state: 'ended' }
    const target = start > currentTime.value ? start : due
    const prefix = start > currentTime.value ? '距开始' : '距结束'
    const minutes = Math.max(1, Math.ceil((target - currentTime.value) / 60000))
    const days = Math.floor(minutes / 1440)
    const hours = Math.floor((minutes % 1440) / 60)
    const remainder = minutes % 60
    const duration = days ? `${days}天${hours ? `${hours}小时` : ''}` : hours ? `${hours}小时${remainder ? `${remainder}分钟` : ''}` : `${remainder}分钟`
    return { label: `${prefix} ${duration}`, state: start > currentTime.value ? 'upcoming' : minutes <= 1440 ? 'urgent' : 'active' }
  }

  function assignmentStateClass(item) {
    if (ctx.role.value !== 'STUDENT') return ''
    if (item.submission_status === 'SUBMITTED') return 'task-completed'
    return new Date(item.due_at) <= new Date() ? 'task-overdue' : ''
  }

  function campaignStateClass(item) {
    if (ctx.role.value !== 'STUDENT') return ''
    if (['COMPLETED', 'SKIPPED'].includes(item.allocation_status)) return 'task-completed'
    return new Date(item.due_at) <= new Date() ? 'task-overdue' : ''
  }

  const statusLabels = { ACTIVE: '进行中', ARCHIVED: '已归档', PENDING: '待处理', PENDING_REVIEW: '待处理', PENDING_COEFFICIENT: '待填系数', PENDING_ASSESSMENT: '待评分', PENDING_REASSESSMENT: '待重新评分', PENDING_SUBMISSION: '待提交', NO_SUBMISSION: '未提交', GRADED: '已评分', CHANGED: '有未发布修改', APPROVED: '已通过', REJECTED: '已拒绝', CANCELLED: '已取消', DRAFT: '待发布', PUBLISHED: '已发布', SUBMITTED: '已提交', RETRACTED: '已撤回', VALID: '有效', INVALID: '已作废', CLOSED: '已结束', NOT_SUBMITTED: '未提交', LEFT: '已退出', DISBANDED: '已解散', NOT_STARTED: '未开始' }

  const roleLabels = { LEADER: '组长', MEMBER: '组员', TEACHER: '教师', STUDENT: '学生', SYSTEM: '系统' }

  const objectLabels = { user: '用户', class: '教学班', class_join_request: '入班申请', team: '小组', team_request: '组队申请', topic: '选题', assignment: '作业', submission: '作业提交', submission_assessment: '提交评价', review_campaign: '互评活动', peer_review: '作品评价', grade: '成绩', role_menu_permissions: '角色菜单权限' }

  const actionLabels = { PASSWORD_CHANGED: '修改密码', PASSWORD_RESET: '重置密码', ROLE_MENU_PERMISSIONS_UPDATED: '更新角色菜单权限', CLASS_CREATED: '创建教学班', CLASS_UPDATED: '更新教学班', CLASS_DELETED: '删除教学班', CLASS_JOIN_REQUESTED: '申请加入教学班', CLASS_JOINED_BY_INVITE: '通过邀请码入班', CLASS_JOIN_APPROVED: '同意入班申请', CLASS_JOIN_REJECTED: '拒绝入班申请', ROSTER_IMPORTED: '导入学生名单', CLASS_MEMBER_ADDED: '添加班级成员', CLASS_MEMBER_UPDATED: '更新成员信息', CLASS_MEMBER_REMOVED: '移出班级成员', TEAM_CREATED: '创建小组', TEAMS_AUTO_GROUPED: '自动分组', TEAM_REQUEST_DECIDED: '处理组队申请', TEAM_REQUEST_CANCELLED: '取消组队申请', TEAM_INVITATION_RESPONDED: '回应小组邀请', TEAM_LEADER_TRANSFERRED: '移交组长', TEAM_LEFT: '退出小组', TEAM_DISBANDED: '解散小组', TEAM_MEMBER_REMOVED: '移出小组成员', TOPIC_SUBMITTED: '提交选题', TOPIC_DECIDED: '审核选题', ASSIGNMENT_CREATED: '创建作业', ASSIGNMENT_UPDATED: '更新作业', ASSIGNMENT_PUBLISHED: '发布作业', ASSIGNMENT_RETRACTED: '撤回作业', ASSIGNMENT_CLOSED: '提前截止作业', ASSIGNMENT_DELETED: '删除作业', SUBMISSION_CREATED: '提交作业', SUBMISSION_RETRACTED: '撤回作业', SUBMISSIONS_EXPORTED: '导出作业', REVIEW_CAMPAIGN_CREATED: '创建互评活动', REVIEW_CAMPAIGN_AUTO_CREATED: '自动创建互评活动', REVIEW_CAMPAIGN_CLOSED: '提前截止互评', PEER_REVIEW_SUBMITTED: '提交作品评价', PEER_REVIEW_UPDATED: '更新作品评价', PEER_REVIEW_INVALIDATED: '作废作品评价', PEER_ASSESSMENT_SUBMITTED: '提交学生互评', PEER_ASSESSMENT_UPDATED: '更新学生互评', TEACHER_ASSESSMENT_SUBMITTED: '提交教师评分', TEACHER_ASSESSMENT_UPDATED: '更新教师评分', TEACHER_ASSESSMENT_CLEARED: '清除教师评分', TEACHER_FEEDBACK_DRAFT_SAVED: '保存教师反馈草稿', TEACHER_FEEDBACK_PUBLISHED: '发布教师反馈', PEER_GRADES_GENERATED: '生成互评成绩', GRADE_COEFFICIENT_UPDATED: '更新小组系数', GRADES_PUBLISHED: '发布成绩' }

  function statusLabel(value) { return statusLabels[value] || value || '-' }

  function assignmentTypeLabel(item) { return `${item.submitter_type === 'INDIVIDUAL' ? '个人' : '小组'}${item.kind === 'EXPERIMENT' ? '实验' : '作业'}` }

  function roleLabel(value) { return roleLabels[value] || value || '-' }

  function objectLabel(value) { return objectLabels[value] || (value ? '其他业务对象' : '-') }

  function actionLabel(value) { return value === 'TEAM_RECRUITMENT_CLOSED' ? '截止小组招募' : value === 'TEAM_RECRUITMENT_OPENED' ? '继续小组招募' : actionLabels[value] || (value ? '其他系统操作' : '-') }

  function gradeSourceLabel(value) { return value === 'TEACHER' ? '教师评分' : value === 'PEER' ? '学生互评' : value === 'SYSTEM' ? '系统判定' : '-' }

  function gradingStatusColor(status) { return status === 'PENDING_REASSESSMENT' ? 'blue' : status === 'PENDING_ASSESSMENT' ? 'orange' : 'default' }

  return { currentTime, iso, idempotencyKey, localDateTime, formatTime, assignmentCountdown, assignmentStateClass, campaignStateClass, statusLabels, roleLabels, objectLabels, actionLabels, statusLabel, assignmentTypeLabel, roleLabel, objectLabel, actionLabel, gradeSourceLabel, gradingStatusColor }
}
