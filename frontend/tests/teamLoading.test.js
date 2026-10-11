import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { ref } from 'vue'

test('team loading reports errors only after failure and clears them on retry or close', async () => {
  const requests = []
  globalThis.teamTestApi = () => new Promise((resolve, reject) => requests.push({ resolve, reject }))
  try {
    const source = (await readFile(new URL('../src/modules/members/composables/useTeams.js', import.meta.url), 'utf8'))
      .replace("import { api, exportArchive } from '../../../api'", 'const api = globalThis.teamTestApi; const exportArchive = api')
      .replace("import { Modal, message } from 'ant-design-vue'", 'const Modal = {}; const message = { error() {} }')
      .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
    const { useTeams } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
    const state = useTeams({ role: ref('STUDENT'), classId: ref('class'), route: { path: '/teams' }, session: {} })
    assert.equal(state.teamDetailError.value, false)
    const first = state.openTeam({ id: 'team' }, { inline: true })
    assert.equal(state.teamDrawerLoading.value, true)
    assert.equal(state.teamDetailError.value, false)
    requests[0].reject(new Error('Request failed'))
    await first
    assert.equal(state.teamDetailError.value, true)
    assert.equal(state.teamDrawerLoading.value, false)
    const retry = state.openTeam({ id: 'team' }, { inline: true })
    assert.equal(state.teamDetailError.value, false)
    requests[1].resolve({ id: 'team', members: [] })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(state.teamDrawerLoading.value, false)
    assert.equal(state.teamModulesLoading.value, true)
    assert.equal(state.teamDetailError.value, false)
    requests[2].resolve({ modules: {} })
    await retry
    const stale = state.openTeam({ id: 'team' }, { inline: true })
    state.closeTeamDrawer()
    requests[3].reject(new Error('Outdated failure'))
    await stale
    assert.equal(state.teamDetailError.value, false)
  } finally {
    delete globalThis.teamTestApi
  }
})
