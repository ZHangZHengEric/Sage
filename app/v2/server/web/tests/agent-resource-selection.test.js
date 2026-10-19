import assert from 'node:assert/strict'
import { test } from 'node:test'
import { agentToolChoices, agentSkillChoices, resourceId, resourceNames, filterResourceChoices, selectResourceResults } from '../src/agent-resource-selection.js'

test('tool picker preserves missing grants and distinguishes identical names in separate scopes', () => {
  const items = agentToolChoices([{ name: 'file_read', source: 'official', category: 'files' }], ['file_read', 'remote_search'], [
    { source: 'mcp', name: '文书_资料', tools: ['file_read'] }, { source: 'a2a', name: '研究助手', tools: ['remote_search'] },
  ], ['missing_builtin'], ['missing_external'])
  assert.equal(new Set(items.map(item => item.id)).size, 5)
  assert.equal(items.find(item => item.id === 'tools:file_read').title, '读取文件')
  assert.equal(items.find(item => item.id === 'external_tools:file_read').title, 'file_read')
  assert.deepEqual(items.filter(item => !item.available).map(item => item.name), ['missing_builtin', 'missing_external'])
  assert.deepEqual(filterResourceChoices(items, new Set(), { query: '文书_资料' }).map(item => item.name), ['file_read'])
  assert.deepEqual(filterResourceChoices(items, new Set(), { source: 'a2a' }).map(item => item.name), ['remote_search'])
})

test('bulk selection covers filtered pages while preserving unrelated and unavailable selections', () => {
  const items = agentToolChoices([], Array.from({ length: 230 }, (_, i) => `query_${i}`), [], [], ['lost'])
  const initial = new Set(['external_tools:lost', 'tools:retained'])
  const results = filterResourceChoices(items, initial, { query: 'query_' })
  const draft = selectResourceResults(initial, results, true)
  assert.equal(draft.size, 232)
  assert.equal(initial.size, 2)
  assert.deepEqual(selectResourceResults(draft, results, false), initial)
  const all = selectResourceResults(new Set(), items, true)
  assert.equal(all.size, 230)
  assert.equal(all.has('external_tools:lost'), false)
})

test('skills retain missing bindings and selected-state filtering works independently of search', () => {
  const items = agentSkillChoices([{ name: 'research', description: '资料整理' }], ['lost'])
  const selected = new Set([resourceId('skills', 'lost')])
  assert.deepEqual(filterResourceChoices(items, selected, { state: 'selected' }).map(item => item.name), ['lost'])
  assert.equal(filterResourceChoices(items, selected, { query: '资料' })[0].name, 'research')
  assert.equal(filterResourceChoices(items, selected, { state: 'unavailable' })[0].available, false)
})


test('undo restores a missing grant even after it drops out of the current catalog', () => {
  const ids = ['tools:file_read', 'external_tools:mcp:old:query', 'skills:missing-skill']
  assert.deepEqual(resourceNames(ids, 'external_tools'), ['mcp:old:query'])
  assert.deepEqual(resourceNames(ids, 'skills'), ['missing-skill'])
})
