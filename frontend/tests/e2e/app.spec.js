import { expect, test } from '@playwright/test'

test('login is empty and contains no sample account', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录课程空间' })).toBeVisible()
  await expect(page.getByPlaceholder('学号 / 工号')).toHaveValue('')
  await expect(page.getByPlaceholder('请输入密码')).toHaveValue('')
  await expect(page.getByText('演示账号')).toHaveCount(0)
})

test('teacher uses top navigation and starts with an empty class list', async ({ page }, testInfo) => {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api/v1', '')
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ message: '请先登录' }) })
    if (path === '/auth/login' && request.method() === 'POST') return json({ user: { id: 'teacher-empty', account: 'teacher', name: '老师', role: 'TEACHER' }, csrf_token: 'test-csrf' })
    if (path === '/classes') return json({ items: [], total: 0 })
    if (path === '/classes/current/context') return json({ user: { id: 'teacher-empty', account: 'teacher', name: '老师', role: 'TEACHER' }, current_class: null, team_membership: null, team_gate_required: false, permissions: { manage_class: true, access_coursework: true } })
    return json({ items: [], total: 0 })
  })
  await page.goto('/login')
  await page.getByText('教师', { exact: true }).click()
  await page.getByPlaceholder('学号 / 工号').fill('teacher')
  await page.getByPlaceholder('请输入密码').fill('123456')
  await page.getByRole('button', { name: '进入课程空间' }).click()
  await expect(page).toHaveURL(/\/overview$/)
  await expect(page.locator('nav.top-nav')).toBeVisible()
  await expect(page.locator('.ant-layout-sider')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '还没有教学班' })).toBeVisible()
  await expect(page.getByText('暂无教学班')).toBeVisible()

  await page.locator('.header-right .ant-btn').first().click()
  await expect(page.getByRole('dialog', { name: '站内通知' })).toBeVisible()
  await expect(page.locator('.ant-drawer')).toHaveCount(0)
  await page.getByRole('button', { name: 'Close' }).click()

  await page.getByRole('button', { name: '创建教学班' }).click()
  const createClassDialog = page.getByRole('dialog', { name: '创建教学班' })
  await expect(createClassDialog.getByRole('button', { name: '取 消' })).toBeVisible()
  await createClassDialog.getByRole('button', { name: '取 消' }).click()

  const bodyBox = await page.locator('body').boundingBox()
  const viewport = page.viewportSize()
  expect(bodyBox.width).toBeLessThanOrEqual(viewport.width)
  await page.screenshot({ path: `test-results/${testInfo.project.name}-empty-dashboard.png`, fullPage: true })
})

test('teacher manages classes and creates coursework for multiple classes', async ({ page }) => {
  const classes = [
    { id: 'class-1', course: '软件工程', semester: '2027 春季', name: '测试一班', status: 'ACTIVE', team_deadline: null, max_team_members: 5, version: 1, member_count: 20, assignment_count: 0, deletable: false },
    { id: 'class-2', course: '软件工程', semester: '2027 春季', name: '测试二班', status: 'ACTIVE', team_deadline: null, max_team_members: 5, version: 1, member_count: 18, assignment_count: 0, deletable: false },
    { id: 'class-3', course: '软件工程', semester: '2027 春季', name: '待删除空班', status: 'ACTIVE', team_deadline: null, max_team_members: 5, version: 1, member_count: 0, assignment_count: 0, deletable: true }
  ]
  const assignments = { 'class-1': [], 'class-2': [], 'class-3': [] }
  const campaigns = { 'class-1': [], 'class-2': [], 'class-3': [] }
  let assignmentPayload
  let assignmentPatch
  let classPatch
  let assignmentClosed = false
  let assignmentRetracted = false
  let assignmentDeleted = false
  let campaignClosed = false

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return json({ user: { id: 'teacher-1', account: 'teacher', name: '老师', role: 'TEACHER' }, csrf_token: 'test-csrf' })
    if (path === '/classes' && request.method() === 'GET') return json({ items: classes, total: classes.length })
    if (path === '/classes/current/context') {
      const selected = classes.find(item => item.id === url.searchParams.get('class_id')) || classes[0] || null
      return json({ user: { id: 'teacher-1', account: 'teacher', name: '老师', role: 'TEACHER' }, current_class: selected, team_membership: null, team_gate_required: false, permissions: { manage_class: true, access_coursework: true } })
    }
    if (path === '/notifications') return json({ items: [], total: 0 })
    if (/^\/classes\/[^/]+\/members$/.test(path)) return json({ items: [], total: 0 })
    if (path === '/assignments' && request.method() === 'GET') {
      const classId = url.searchParams.get('class_id'); return json({ items: assignments[classId] || [], total: (assignments[classId] || []).length })
    }
    if (path === '/review-campaigns' && request.method() === 'GET') {
      const classId = url.searchParams.get('class_id'); return json({ items: campaigns[classId] || [], total: (campaigns[classId] || []).length })
    }
    if (/^\/assignments\/[^/]+\/files$/.test(path)) return json({ attachments: [], drafts: [] })
    if (/^\/assignments\/[^/]+\/submissions$/.test(path)) return json({ items: [], total: 0 })
    if (path === '/assignments/bulk' && request.method() === 'POST') {
      assignmentPayload = request.postDataJSON()
      const items = assignmentPayload.class_ids.map((classId, index) => ({ id: `assignment-${index + 1}`, class_id: classId, title: assignmentPayload.title, description: assignmentPayload.description, submitter_type: assignmentPayload.submitter_type, due_at: assignmentPayload.due_at, auto_review_enabled: assignmentPayload.auto_review_enabled, auto_review_mode: assignmentPayload.auto_review_mode, auto_review_criteria_text: assignmentPayload.auto_review_criteria_text, auto_review_due_at: assignmentPayload.auto_review_due_at, auto_review_status: 'PENDING', status: 'DRAFT', version: 1 }))
      items.forEach(item => { assignments[item.class_id].push(item); classes.find(course => course.id === item.class_id).assignment_count += 1 })
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ items, total: items.length }) })
    }
    const publishMatch = path.match(/^\/assignments\/([^/]+)\/publish$/)
    if (publishMatch && request.method() === 'POST') {
      const item = Object.values(assignments).flat().find(row => row.id === publishMatch[1]); item.status = 'PUBLISHED'; return json(item)
    }
    const closeAssignmentMatch = path.match(/^\/assignments\/([^/]+)\/close$/)
    if (closeAssignmentMatch && request.method() === 'POST') {
      const item = Object.values(assignments).flat().find(row => row.id === closeAssignmentMatch[1]); Object.assign(item, { status: 'CLOSED', due_at: new Date().toISOString(), version: item.version + 1 }); assignmentClosed = true
      if (!campaigns[item.class_id].some(record => record.assignment_id === item.id)) campaigns[item.class_id].push({ id: 'campaign-1', assignment_id: item.id, assignment_title: item.title, mode: item.auto_review_mode, criteria_text: item.auto_review_criteria_text, due_at: item.auto_review_due_at, status: 'ACTIVE', grades_generated_at: null, version: 1 })
      return json(item)
    }
    const retractAssignmentMatch = path.match(/^\/assignments\/([^/]+)\/retract$/)
    if (retractAssignmentMatch && request.method() === 'POST') {
      const item = Object.values(assignments).flat().find(row => row.id === retractAssignmentMatch[1]); Object.assign(item, { status: 'DRAFT', version: item.version + 1 }); assignmentRetracted = true; return json(item)
    }
    const assignmentMatch = path.match(/^\/assignments\/([^/]+)$/)
    if (assignmentMatch && request.method() === 'PATCH') {
      assignmentPatch = request.postDataJSON(); const item = Object.values(assignments).flat().find(row => row.id === assignmentMatch[1]); Object.assign(item, assignmentPatch, { version: item.version + 1 }); return json(item)
    }
    if (assignmentMatch && request.method() === 'DELETE') {
      for (const items of Object.values(assignments)) {
        const index = items.findIndex(item => item.id === assignmentMatch[1])
        if (index >= 0) items.splice(index, 1)
      }
      assignmentDeleted = true; return route.fulfill({ status: 204 })
    }
    if (path === '/review-campaigns/campaign-1/stats') return json({ assigned_count: 20, completed_count: 0, skipped_count: 0, completion_rate: 0 })
    if (path === '/review-campaigns/campaign-1/reviews') return json({ items: [], total: 0 })
    if (path === '/review-campaigns/campaign-1/close' && request.method() === 'POST') {
      Object.assign(campaigns['class-1'][0], { status: 'CLOSED', due_at: new Date().toISOString(), version: 2 }); campaignClosed = true; return json(campaigns['class-1'][0])
    }
    const classMatch = path.match(/^\/classes\/([^/]+)$/)
    if (classMatch && request.method() === 'PATCH') {
      classPatch = request.postDataJSON(); const item = classes.find(course => course.id === classMatch[1]); Object.assign(item, classPatch, { version: item.version + 1 }); return json(item)
    }
    if (classMatch && request.method() === 'DELETE') {
      classes.splice(classes.findIndex(item => item.id === classMatch[1]), 1); return route.fulfill({ status: 204 })
    }
    return json({ items: [], total: 0 })
  })

  await page.goto('/classes')
  await expect(page.getByRole('heading', { name: '教学班' })).toBeVisible()
  await expect(page.locator('.class-list-panel')).toContainText('测试一班')
  await expect(page.locator('.class-list-panel')).toContainText('待删除空班')

  const firstRow = page.locator('.class-list-panel tbody tr').filter({ hasText: '测试一班' })
  await firstRow.getByRole('button').nth(1).click()
  const classDialog = page.getByRole('dialog', { name: '编辑教学班' })
  await classDialog.locator('.ant-form-item').filter({ hasText: '班级名称' }).locator('input').fill('测试 A 班')
  await classDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  await expect.poll(() => classPatch?.name).toBe('测试 A 班')

  await page.getByRole('button', { name: '作业管理' }).click()
  await page.getByRole('button', { name: '新建作业' }).click()
  const assignmentDialog = page.getByRole('dialog', { name: '新建作业' })
  await expect(assignmentDialog.getByRole('button', { name: '取 消' })).toBeVisible()
  await assignmentDialog.locator('.ant-form-item').filter({ hasText: '教学班' }).locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: '测试二班' }).click()
  await assignmentDialog.locator('.ant-form-item').filter({ hasText: '标题' }).locator('input').fill('跨班需求报告')
  await assignmentDialog.locator('.ant-form-item').filter({ hasText: '截止时间' }).locator('input').fill('2027-12-01T12:00')
  await assignmentDialog.locator('.tiptap').fill('完成需求分析并提交。')
  await assignmentDialog.locator('.modal-actions .ant-btn-primary').click()
  await expect.poll(() => assignmentPayload?.class_ids.length).toBe(2)
  expect(assignmentPayload).toMatchObject({ auto_review_enabled: false })
  await expect(page.getByText('已发布', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('PUBLISHED', { exact: true })).toHaveCount(0)
  const assignmentRow = page.locator('.assignment-row').filter({ hasText: '跨班需求报告' }).first()
  await expect(assignmentRow.getByRole('button', { name: '详情', exact: true })).toBeVisible()
  await expect(assignmentRow.getByRole('button', { name: '提交情况', exact: true })).toBeVisible()
  await assignmentRow.getByRole('button', { name: '详情', exact: true }).click()
  await expect(page).toHaveURL(/\/assignments\/assignment-1$/)
  const assignmentDetail = page.locator('.assignment-workspace')
  await expect(page.locator('.assignment-detail-drawer')).toBeVisible()
  const headerBox = await page.locator('.app-header').boundingBox()
  const drawerBox = await page.locator('.assignment-detail-drawer').boundingBox()
  expect(drawerBox.y).toBe(0)
  expect(drawerBox.y).toBeLessThan(headerBox.y + headerBox.height)
  await expect(page.locator('.app-header')).toHaveCSS('z-index', '15')
  await expect(page.locator('.assignment-detail-drawer')).toHaveCSS('z-index', '900')
  await expect(assignmentDetail).toBeVisible()
  await expect(assignmentDetail.getByRole('tab', { name: '详情' })).toBeVisible()
  await expect(assignmentDetail.getByRole('tab', { name: '提交情况' })).toBeVisible()
  await expect(assignmentDetail.getByRole('tab')).toHaveCount(2)
  await expect(page.locator('nav.top-nav').getByRole('button', { name: '互评管理' })).toHaveCount(0)
  await assignmentDetail.getByRole('tab', { name: '提交情况' }).click()
  await expect(assignmentDetail.getByText('提交概览')).toBeVisible()
  await assignmentDetail.getByRole('tab', { name: '详情' }).click()
  await assignmentDetail.getByRole('button', { name: '编辑作业' }).click()
  const editAssignmentDialog = page.getByRole('dialog', { name: '编辑作业' })
  await editAssignmentDialog.locator('.tiptap').fill('更新后的作业说明。')
  await editAssignmentDialog.getByRole('button', { name: '保存修改' }).click()
  await expect.poll(() => assignmentPatch?.description).toContain('更新后的作业说明。')
  expect(assignmentPatch?.version).toBe(1)

  await assignmentDetail.getByRole('button', { name: '提前截止' }).click()
  await page.getByRole('button', { name: '确认截止' }).click()
  await expect.poll(() => assignmentClosed).toBe(true)
  await expect(page.locator('.assignment-detail-drawer')).toBeVisible()
  await expect(page.locator('.content-wrap > .ant-spin-nested-loading > .ant-spin-spinning')).toHaveCount(0)

  await page.locator('.assignment-detail-drawer').getByRole('button', { name: '返回作业列表' }).click()
  await page.locator('.assignment-row').filter({ hasText: '跨班需求报告' }).click()
  const closedAssignmentDetail = page.locator('.assignment-workspace')
  await closedAssignmentDetail.getByRole('button', { name: '撤回发布' }).click()
  await page.getByRole('button', { name: '确认撤回' }).click()
  await expect.poll(() => assignmentRetracted).toBe(true)
  await closedAssignmentDetail.getByRole('button', { name: '删除作业' }).click()
  await page.getByRole('button', { name: '永久删除' }).click()
  await expect.poll(() => assignmentDeleted).toBe(true)

  await page.getByRole('button', { name: '教学班' }).click()
  const disposableRow = page.locator('.class-list-panel tbody tr').filter({ hasText: '待删除空班' })
  await disposableRow.getByRole('button').last().click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page.locator('.class-list-panel')).not.toContainText('待删除空班')
})

test('teacher opens submission preview directly and can override the peer grade', async ({ page }) => {
  let teacherGradePayload
  const peerReviewRequests = []
  const group = { team_id: 'team-1', team_name: '第一小组', draft_value: null, published_value: null, version: 1, member_count: 2 }
  const detail = {
    assignment: { id: 'assignment-grade', title: '需求分析报告', campaign_status: 'CLOSED', grades_generated_at: '2026-09-16T08:00:00Z' },
    groups: [group],
    items: [
      { id: 'grade-1', student_no: '20260001', student_name: '张同学', team_id: 'team-1', team_name: '第一小组', peer_score: 90, draft_coefficient: null, published_coefficient: null, draft_score: null, score: null, status: 'PENDING_COEFFICIENT', has_unpublished_changes: false },
      { id: 'grade-2', student_no: '20260002', student_name: '李同学', team_id: 'team-1', team_name: '第一小组', peer_score: null, draft_coefficient: null, published_coefficient: null, draft_score: null, score: null, status: 'PENDING_REVIEW', has_unpublished_changes: false }
    ],
    total: 2,
    summary: { publishable: 0, pending: 1, changed: 0, published: 0 }
  }

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    if (path.includes('/peer-review')) peerReviewRequests.push(path)
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return json({ user: { id: 'teacher-1', account: 'teacher', name: '老师', role: 'TEACHER' }, csrf_token: 'test-csrf' })
    if (path === '/classes') return json({ items: [{ id: 'class-1', semester: '2026 秋季', name: '软件工程 1 班', status: 'ACTIVE' }], total: 1 })
    if (path === '/classes/current/context') return json({ user: { id: 'teacher-1', role: 'TEACHER' }, current_class: { id: 'class-1', semester: '2026 秋季', name: '软件工程 1 班', status: 'ACTIVE' }, team_gate_required: false })
    if (path === '/notifications') return json({ items: [], total: 0 })
    if (path === '/grades/assignments' && request.method() === 'GET') return json({ items: [{ id: 'assignment-grade', title: '需求分析报告', campaign_status: 'CLOSED', total: 2, pending: 1, ready: 0, published: 0 }], total: 1 })
    if (path === '/assignments' && request.method() === 'GET') return json({ items: [{ id: 'assignment-grade', class_id: 'class-1', title: '需求分析报告', description: '<p>完成需求分析。</p>', submitter_type: 'INDIVIDUAL', due_at: '2026-09-15T08:00:00Z', status: 'CLOSED', version: 2 }], total: 1 })
    if (path === '/assignments/assignment-grade/files') return json({ attachments: [], review_criteria: [], drafts: [] })
    if (path === '/assignments/assignment-grade/submissions') return json({ items: [{ id: 'submission-1', user_id: 'student-1', owner: '张同学', student_no: '20260001', team_id: 'team-1', team_name: '第一小组', status: 'SUBMITTED', submitted_at: '2026-09-15T08:00:00Z', files: [{ id: 'student-file-1', name: '报告.pdf', previewable: true, preview_status: 'READY' }, { id: 'student-file-2', name: '原型.pdf', previewable: true, preview_status: 'READY' }], peer_grade: 'A', peer_review_count: 2, teacher_grade: null, final_grade: 'A', grade_source: 'PEER' }], total: 1 })
    if (/^\/files\/student-file-[12]\/preview$/.test(path)) return route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF-1.4' })
    if (path === '/assignments/assignment-grade/submissions/student-1/grade' && request.method() === 'POST') {
      teacherGradePayload = request.postDataJSON()
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ grade: teacherGradePayload.grade, comment: teacherGradePayload.comment, result: { teacher_grade: { grade: teacherGradePayload.grade, comment: teacherGradePayload.comment }, peer_grade: 'A', peer_review_count: 2, final_grade: teacherGradePayload.grade, grade_source: 'TEACHER' } }) })
    }
    if (path === '/teams') return json({ items: [], total: 0 })
    if (path === '/review-campaigns') return json({ items: [{ id: 'campaign-grade', assignment_id: 'assignment-grade', assignment_title: '需求分析报告', mode: 'TEAM', criteria_text: '按完整性评分', due_at: '2026-09-16T08:00:00Z', status: 'CLOSED', grades_generated_at: '2026-09-16T08:00:00Z' }], total: 1 })
    if (path === '/review-campaigns/campaign-grade/stats') return json({ assigned_count: 2, completed_count: 1, skipped_count: 0, completion_rate: 50 })
    if (path === '/review-campaigns/campaign-grade/reviews') return json({ items: [], total: 0 })
    if (path === '/grades/assignments/assignment-grade' && request.method() === 'GET') return json(detail)
    if (path === '/grades/assignments/assignment-grade/teams/team-1/coefficient' && request.method() === 'PATCH') {
      coefficientPayload = request.postDataJSON()
      Object.assign(group, { draft_value: coefficientPayload.coefficient, version: 2 })
      Object.assign(detail.items[0], { draft_coefficient: coefficientPayload.coefficient, draft_score: 99, status: 'DRAFT' })
      detail.summary.publishable = 1
      return json(group)
    }
    if (path === '/grades/assignments/assignment-grade/publish' && request.method() === 'POST') {
      publishPayload = request.postDataJSON()
      Object.assign(detail.items[0], { score: 99, status: 'PUBLISHED' })
      detail.summary.published = 1
      return json({ published: 1, pending: 1, changed: 0 })
    }
    if (path === '/exports/grades.csv') return route.fulfill({ status: 200, headers: { 'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename="grades.csv"' }, body: '作业,学号,姓名\n需求分析报告,20260001,张同学' })
    return json({ items: [], total: 0 })
  })

  await page.goto('/grades')
  await expect(page.getByRole('heading', { name: '成绩与导出' })).toBeVisible()
  await expect(page.locator('.export-item')).toHaveCount(4)
  await expect(page.locator('.export-item')).toContainText(['成员名单', '小组名单', '互评记录', '作业成绩'])
  await page.locator('.export-grade-item .ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: '需求分析报告' }).click()
  const download = page.waitForEvent('download')
  await page.locator('.export-grade-item').getByRole('button', { name: /CSV/ }).click()
  await download

  await page.goto('/assignments/assignment-grade?tab=submission')
  expect(peerReviewRequests).toEqual([])
  const workspace = page.locator('.assignment-workspace')
  await expect(workspace.getByRole('tab', { name: '提交情况', selected: true })).toBeVisible()
  await workspace.getByRole('button', { name: '查看作业' }).click()
  const preview = page.locator('.file-preview-drawer')
  await expect(preview).toBeVisible()
  await expect(preview.getByText('1 / 2')).toBeVisible()
  await expect(preview.locator('.ant-select')).toContainText('报告.pdf')
  await preview.locator('.preview-grade-form .ant-select').click()
  await page.getByRole('option', { name: 'B', exact: true }).click()
  await preview.locator('textarea').fill('教师复核后评级。')
  await preview.getByRole('button', { name: '保存教师评分' }).click()
  await expect.poll(() => teacherGradePayload).toEqual({ grade: 'B', comment: '教师复核后评级。' })
  await expect(preview).toContainText('最终 B · 教师')
})

test('logout removes the protected view and shows login without a reload', async ({ page }) => {
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const body = path === '/auth/session'
      ? { user: { id: 'teacher-1', account: 'teacher', name: '老师', role: 'TEACHER' }, csrf_token: 'test-csrf' }
      : path === '/classes' ? { items: [], total: 0 }
        : path === '/classes/current/context' ? { current_class: null, team_gate_required: false }
          : { items: [], total: 0 }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/overview')
  await expect(page.locator('.app-shell')).toBeVisible()
  await page.locator('.user-chip').click()
  await page.getByText('退出登录', { exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: '登录课程空间' })).toBeVisible()
  await expect(page.locator('.app-shell')).toHaveCount(0)
  expect(pageErrors).toEqual([])
})

test('expired session switches from the protected view to login', async ({ page }) => {
  let expired = false
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    if (path === '/assignments' && expired) {
      return route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ message: '请先登录' }) })
    }
    const body = path === '/auth/session'
      ? { user: { id: 'teacher-1', account: 'teacher', name: '老师', role: 'TEACHER' }, csrf_token: 'test-csrf' }
      : path === '/classes' ? { items: [{ id: 'class-1', semester: '2026 秋季', name: '软件工程一班', status: 'ACTIVE' }], total: 1 }
        : path === '/classes/current/context' ? { current_class: { id: 'class-1', name: '软件工程一班', status: 'ACTIVE' }, team_gate_required: false }
          : { items: [], total: 0 }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/classes')
  await expect(page.locator('.app-shell')).toBeVisible()
  expired = true
  await page.getByRole('button', { name: '作业管理' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: '登录课程空间' })).toBeVisible()
  await expect(page.locator('.app-shell')).toHaveCount(0)
  expect(pageErrors).toEqual([])
})

test('student selects submitted teammates and grades their latest work from A to E', async ({ page }) => {
  const reviewPayloads = []
  const assignment = { assignment_id: 'assignment-direct', assignment_title: '需求分析报告', title: '需求分析报告', due_at: '2099-01-01T00:00:00Z', available_count: 2, reviewed_count: 0, pending_count: 2 }
  const task = { assignment, team: { id: 'team-1', name: '第一小组' }, candidates: [
    { user_id: 'student-2', name: '李同学', student_no: '20260002', submitted_at: '2026-09-14T08:00:00Z', files: [{ id: 'file-1', name: 'report.pdf' }], review: null },
    { user_id: 'student-3', name: '王同学', student_no: '20260003', submitted_at: '2026-09-15T08:00:00Z', files: [{ id: 'file-2', name: 'prototype.pdf' }], review: null }
  ] }

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return json({ user: { id: 'student-1', account: '20260001', name: '张同学', role: 'STUDENT' }, csrf_token: 'student-csrf' })
    if (path === '/classes') return json({ items: [{ id: 'class-1', semester: '2026 秋季', name: '软件工程 1 班', status: 'ACTIVE' }], total: 1 })
    if (path === '/classes/current/context') return json({ user: { id: 'student-1', account: '20260001', name: '张同学', role: 'STUDENT' }, current_class: { id: 'class-1', semester: '2026 秋季', name: '软件工程 1 班', status: 'ACTIVE' }, team_membership: { team_id: 'team-1' }, team_gate_required: false, permissions: { access_coursework: true } })
    if (path === '/notifications') return json({ items: [], total: 0 })
    if (path === '/peer-review-assignments' && request.method() === 'GET') return json({ items: [assignment], total: 1 })
    if (path === '/assignments/assignment-direct/peer-review' && request.method() === 'GET') return json(task)
    if (path === '/assignments/assignment-direct/peer-reviews' && request.method() === 'POST') {
      const payload = request.postDataJSON(); reviewPayloads.push(payload)
      const candidate = task.candidates.find(item => item.user_id === payload.reviewee_id)
      candidate.review = { id: `review-${reviewPayloads.length}`, grade: payload.grade, comment: payload.comment }
      assignment.reviewed_count = task.candidates.filter(item => item.review).length
      assignment.pending_count = assignment.available_count - assignment.reviewed_count
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ...candidate.review, updated: reviewPayloads.length > 1 }) })
    }
    return json({ items: [], total: 0 })
  })

  await page.goto('/reviews')
  await page.locator('.assignment-row').filter({ hasText: '需求分析报告' }).click()
  await expect(page).toHaveURL(/\/reviews\/assignment-direct$/)
  const detail = page.locator('.review-workspace')
  await expect(detail).toContainText('李同学')
  await expect(detail).toContainText('20260002')
  await detail.getByText('B', { exact: true }).click()
  await detail.locator('textarea').fill('结构完整，论证清晰。')
  await detail.getByRole('button', { name: '提交评价' }).click()
  await expect.poll(() => reviewPayloads).toEqual([{ reviewee_id: 'student-2', grade: 'B', comment: '结构完整，论证清晰。' }])
  await expect(detail.getByRole('button', { name: '更新评价' })).toBeVisible()
  await detail.getByText('A', { exact: true }).click()
  await detail.locator('textarea').fill('补充检查后，论证也很充分。')
  await detail.getByRole('button', { name: '更新评价' }).click()
  await expect.poll(() => reviewPayloads).toEqual([
    { reviewee_id: 'student-2', grade: 'B', comment: '结构完整，论证清晰。' },
    { reviewee_id: 'student-2', grade: 'A', comment: '补充检查后，论证也很充分。' }
  ])
})

test('student assignment detail submits every uploaded file without selection controls', async ({ page }) => {
  let submissionPayload
  const assignment = { id: 'assignment-detail', class_id: 'class-1', title: '需求分析报告', description: '<p>完成需求分析并提交报告。</p>', submitter_type: 'INDIVIDUAL', starts_at: null, due_at: '2099-01-01T00:00:00Z', allow_late: false, status: 'PUBLISHED', submission_status: 'SUBMITTED' }
  const files = [
    { id: 'file-1', name: '需求分析报告.pdf', previewable: true, download_only: false, submitted: true },
    { id: 'file-2', name: '补充说明.md', previewable: true, download_only: false, submitted: false },
  ]
  const materials = [
    { id: 'material-1', name: '作业模板.pdf', previewable: true, download_only: false, preview_status: 'READY' },
    { id: 'material-2', name: '参考答案.docx', previewable: false, download_only: true, preview_status: 'NOT_AVAILABLE' },
  ]

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return json({ user: { id: 'student-1', account: '20260001', name: '张同学', role: 'STUDENT' }, csrf_token: 'student-csrf' })
    if (path === '/classes') return json({ items: [{ id: 'class-1', semester: '2026 秋季', name: '软件工程 1 班', status: 'ACTIVE' }], total: 1 })
    if (path === '/classes/current/context') return json({ user: { id: 'student-1', account: '20260001', name: '张同学', role: 'STUDENT' }, current_class: { id: 'class-1', semester: '2026 秋季', name: '软件工程 1 班', status: 'ACTIVE' }, team_membership: { team_id: 'team-1' }, team_gate_required: false, permissions: { access_coursework: true } })
    if (path === '/notifications') return json({ items: [], total: 0 })
    if (path === '/assignments' && request.method() === 'GET') return json({ items: [assignment], total: 1 })
    if (path === '/assignments/assignment-detail/files') return json({ attachments: materials, review_criteria: [], drafts: files })
    if (path === '/files/material-1/preview') return route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>作业模板预览</h1>' })
    if (path === '/assignments/assignment-detail/submission' && request.method() === 'GET') return json({ status: 'SUBMITTED', submitted_at: '2026-09-15T08:00:00Z', is_late: false, files: [files[0]] })
    if (path === '/assignments/assignment-detail/submission' && request.method() === 'POST') {
      submissionPayload = request.postDataJSON()
      return json({ id: 'submission-1', submitted_at: '2026-09-16T08:00:00Z', is_late: false }, 201)
    }
    return json({ items: [], total: 0 })
  })

  await page.goto('/assignments/assignment-detail')
  const workspace = page.locator('.assignment-workspace')
  await expect(workspace.getByRole('tab', { name: '作业详情' })).toBeVisible()
  await expect(workspace).toContainText('作业资料')
  await expect(workspace).toContainText('作业模板.pdf')
  const detailUrl = page.url()
  await workspace.getByRole('button', { name: '作业模板.pdf' }).click()
  const previewDrawer = page.locator('.file-preview-drawer')
  await expect(previewDrawer).toBeVisible()
  await expect(previewDrawer.locator('iframe')).toHaveCount(1)
  expect(page.url()).toBe(detailUrl)
  await previewDrawer.getByRole('button', { name: 'Close' }).click()
  await workspace.getByRole('button', { name: /参考答案\.docx/ }).click()
  await expect(previewDrawer.getByText('无法在线预览')).toBeVisible()
  await expect(previewDrawer).toContainText('该文件格式暂不支持在线预览')
  await previewDrawer.getByRole('button', { name: 'Close' }).click()
  await workspace.getByRole('tab', { name: '提交作业' }).click()
  await expect(workspace.getByText('已提交', { exact: true })).toBeVisible()
  await expect(workspace.locator('input[type="checkbox"]')).toHaveCount(0)
  await expect(workspace).not.toContainText('本次保留')
  await workspace.getByRole('button', { name: '更新提交' }).click()
  await page.getByRole('button', { name: '确认更新' }).click()
  await expect.poll(() => submissionPayload).toEqual({})
})
