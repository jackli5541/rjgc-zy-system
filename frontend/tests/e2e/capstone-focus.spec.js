import { expect, test } from '@playwright/test'

test('student capstone focus mode preserves edits and restores the page', async ({ page }) => {
  const user = { id: 'student-focus', name: '测试同学', account: '20260001', role: 'STUDENT' }
  const currentClass = { id: 'class-focus', semester: '2026 秋季', name: '软件工程', status: 'ACTIVE' }
  const document = { id: 'doc-focus', name: '立项书.md', stage: 'PROPOSAL', sort_order: 0, revision: 1 }
  const basePath = `/capstone/classes/${currentClass.id}/workspace`
  let markdown = '# 初始标题\n\n正文'
  let revision = 1
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace('/api/v1', '')
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/auth/session') return json({ user, csrf_token: 'student-csrf' })
    if (path === '/classes') return json({ items: [currentClass], total: 1 })
    if (path === '/classes/current/context') return json({ user, current_class: currentClass, team_gate_required: false, permissions: { access_coursework: true } })
    if (path === basePath) return json({ id: 'workspace-focus', documents: [document], locked: false })
    if (path === `${basePath}/documents/${document.id}`) {
      if (request.method() === 'PUT') {
        markdown = request.postDataJSON().markdown_content
        revision += 1
      }
      return json({ ...document, markdown_content: markdown, revision })
    }
    if (path.endsWith('/teammates')) return json({ members: [], team_name: '测试小组', topic_name: '测试课题' })
    return json({ items: [], total: 0 })
  })

  await page.goto('/capstone')
  const capstone = page.locator('.capstone-page')
  const workspace = capstone.locator('.markdown-workspace')
  const editor = workspace.locator('.tiptap')
  await expect(editor.locator('h1')).toHaveText('初始标题')
  const readerHeight = await workspace.locator('.workspace-document-reader').evaluate(element => element.getBoundingClientRect().height)
  await workspace.getByRole('button', { name: '专注编辑', exact: true }).click()
  await expect(workspace.getByRole('button', { name: '退出专注', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.app-header')).toBeHidden()
  await expect(capstone.locator('.capstone-title')).toBeHidden()
  await expect(capstone.locator('.teaching-materials-tree')).toBeHidden()
  await expect(capstone.locator('.capstone-teammates')).toBeHidden()
  await expect.poll(() => workspace.locator('.workspace-document-reader').evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThan(readerHeight)
  await editor.locator('h1').fill('专注编辑后的标题')
  await expect(workspace.getByRole('navigation', { name: '文档大纲' })).toContainText('专注编辑后的标题')
  await workspace.getByRole('button', { name: /保\s*存/, exact: true }).click()
  await expect.poll(() => markdown).toContain('专注编辑后的标题')
  await workspace.getByRole('button', { name: '退出专注', exact: true }).click()
  await expect(page.locator('.app-header')).toBeVisible()
  await expect(capstone.locator('.capstone-title')).toBeVisible()
  await expect(capstone.locator('.teaching-materials-tree')).toBeVisible()
  await expect(capstone.locator('.capstone-teammates')).toBeVisible()
  await expect(editor.locator('h1')).toHaveText('专注编辑后的标题')
})
