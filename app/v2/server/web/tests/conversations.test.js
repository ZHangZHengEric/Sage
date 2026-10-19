import assert from 'node:assert/strict'
import { test } from 'node:test'
import { conversationAgent, newestThreads } from '../src/conversations.js'

test('flat history sorts by update time, retains invalid dates and leaves the source unchanged', () => {
  const items = [{ thread_id: 'old', updated_at: '2026-10-18T00:00:00Z' }, { thread_id: 'unknown', updated_at: 'invalid' }, { thread_id: 'new', updated_at: '2026-10-19T00:00:00Z' }]
  assert.deepEqual(newestThreads(items).map(item => item.thread_id), ['new', 'old', 'unknown'])
  assert.equal(items[0].thread_id, 'old')
})

test('same agent id from another owner never borrows the current user name', () => {
  const agents = [{ id: 'same', name: '我的助手' }, { id: 'same', name: '团队助手', _owner: { user_id: 'alice' } }]
  assert.equal(conversationAgent({ agent_id: 'same' }, agents, 'me'), '我的助手')
  assert.equal(conversationAgent({ agent_id: 'same', _owner: { user_id: 'alice' } }, agents, 'me'), '团队助手')
  assert.equal(conversationAgent({ agent_id: 'same', _owner: { user_id: 'bob' } }, agents, 'me'), 'same')
})
