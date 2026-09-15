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
    if (path === '/auth/login' && request.method() === 'POST') return json({ user: { id: 'teacher-empty', account: 'teacher', name: '王老师', role: 'TEACHER' }, csrf_token: 'test-csrf' })
    if (path === '/classes') return json({ items: [], total: 0 })
    if (path === '/classes/current/context') return json({ user: { id: 'teacher-empty', account: 'teacher', name: '王老师', role: 'TEACHER' }, current_class: null, team_membership: null, team_gate_required: false, permissions: { manage_class: true, access_coursework: true } })
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
  let campaignPayload
  let classPatch

  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return json({ user: { id: 'teacher-1', account: 'teacher', name: '王老师', role: 'TEACHER' }, csrf_token: 'test-csrf' })
    if (path === '/classes' && request.method() === 'GET') return json({ items: classes, total: classes.length })
    if (path === '/classes/current/context') {
      const selected = classes.find(item => item.id === url.searchParams.get('class_id')) || classes[0] || null
      return json({ user: { id: 'teacher-1', account: 'teacher', name: '王老师', role: 'TEACHER' }, current_class: selected, team_membership: null, team_gate_required: false, permissions: { manage_class: true, access_coursework: true } })
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
      const items = assignmentPayload.class_ids.map((classId, index) => ({ id: `assignment-${index + 1}`, class_id: classId, title: assignmentPayload.title, description: assignmentPayload.description, submitter_type: assignmentPayload.submitter_type, due_at: assignmentPayload.due_at, status: 'PUBLISHED', version: 1 }))
      items.forEach(item => { assignments[item.class_id].push(item); classes.find(course => course.id === item.class_id).assignment_count += 1 })
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ items, total: items.length }) })
    }
    const assignmentMatch = path.match(/^\/assignments\/([^/]+)$/)
    if (assignmentMatch && request.method() === 'PATCH') {
      assignmentPatch = request.postDataJSON(); const item = Object.values(assignments).flat().find(row => row.id === assignmentMatch[1]); Object.assign(item, assignmentPatch, { version: item.version + 1 }); return json(item)
    }
    if (path === '/review-campaigns/bulk' && request.method() === 'POST') {
      campaignPayload = request.postDataJSON()
      const items = campaignPayload.targets.map((target, index) => ({ id: `campaign-${index + 1}`, ...target, assignment_title: assignments[target.class_id].find(item => item.id === target.assignment_id).title, rubric: campaignPayload.rubric, due_at: campaignPayload.due_at, status: 'ACTIVE' }))
      items.forEach(item => campaigns[item.class_id].push(item))
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ items, total: items.length }) })
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
  await assignmentDialog.locator('.ant-form-item').filter({ hasText: '说明' }).locator('textarea').fill('完成需求分析并提交。')
  await assignmentDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  await expect.poll(() => assignmentPayload?.class_ids.length).toBe(2)
  await expect(page.getByText('已发布', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('PUBLISHED', { exact: true })).toHaveCount(0)
  await page.locator('.assignment-row').filter({ hasText: '跨班需求报告' }).first().click()
  const assignmentDetail = page.locator('.ant-modal-wrap:visible').filter({ hasText: '作业附件' })
  await expect(assignmentDetail).toBeVisible()
  await assignmentDetail.getByRole('button', { name: '编辑作业' }).click()
  const editAssignmentDialog = page.getByRole('dialog', { name: '编辑作业' })
  await editAssignmentDialog.locator('.ant-form-item').filter({ hasText: '说明' }).locator('textarea').fill('更新后的作业说明。')
  await editAssignmentDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  await expect.poll(() => assignmentPatch?.description).toBe('更新后的作业说明。')
  expect(assignmentPatch?.version).toBe(1)

  await page.getByRole('button', { name: '互评管理' }).click()
  await page.getByRole('button', { name: '开启互评' }).click()
  const campaignDialog = page.getByRole('dialog', { name: '开启组内作品互评' })
  await campaignDialog.locator('.ant-form-item').filter({ hasText: '教学班' }).locator('.ant-select-selector').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: '测试二班' }).click()
  for (const className of ['测试 A 班', '测试二班']) {
    const item = campaignDialog.locator('.ant-form-item').filter({ hasText: `${className}的个人作业` })
    await item.locator('.ant-select-selector').click()
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Enter')
  }
  await campaignDialog.locator('.ant-form-item').filter({ hasText: '评分维度' }).locator('input').first().fill('完成质量')
  await campaignDialog.locator('.ant-form-item').filter({ hasText: '截止时间' }).locator('input').fill('2027-12-10T12:00')
  await campaignDialog.locator('.ant-modal-footer .ant-btn-primary').click()
  await expect.poll(() => campaignPayload?.targets.length).toBe(2)

  await page.getByRole('button', { name: '教学班' }).click()
  const disposableRow = page.locator('.class-list-panel tbody tr').filter({ hasText: '待删除空班' })
  await disposableRow.getByRole('button').last().click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(page.locator('.class-list-panel')).not.toContainText('待删除空班')
})
