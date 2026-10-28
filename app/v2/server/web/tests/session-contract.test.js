import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAguiAgent, runAgui } from '../src/agui/session.js'
import { updateToolStates, toolStateLabels } from '../src/agui/tool-state.js'
import { messagesFromEvents } from '../src/agui/replay.js'

test('page transport sends the same session_id and compatibility threadId', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const body = JSON.parse(init.body)
    assert.equal(body.session_id, 'Kept-ID')
    assert.equal(body.threadId, 'Kept-ID')
    return new Response([
      { type: 'RUN_STARTED', threadId: body.session_id, session_id: body.session_id, runId: body.runId },
      { type: 'RUN_FINISHED', threadId: body.session_id, session_id: body.session_id, runId: body.runId },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), {
      headers: { 'Content-Type': 'text/event-stream' },
    })
  })
  const agent = createAguiAgent()
  agent.threadId = 'Kept-ID'
  await agent.runAgent({ runId: 'r1', tools: [], context: [] })
  assert.equal(agent.threadId, 'Kept-ID')
})

test('known pre-execution denials remain not executed in live and replayed results', () => {
  const sequence = [
    { type: 'TOOL_CALL_START', toolCallId: 'todo', toolCallName: 'todo_write', parentMessageId: 'p' },
    { type: 'TOOL_CALL_END', toolCallId: 'todo' },
    { type: 'CUSTOM', name: 'tool.call.failed', value: { tool_call_id: 'todo', error: {
      code: 'tool.session_mismatch', metadata: { side_effect_state: 'not_applied' },
    } } },
    { type: 'TOOL_CALL_RESULT', toolCallId: 'todo', messageId: 'result', content: 'session mismatch' },
    { type: 'CUSTOM', name: 'sage.run.failed' },
  ]
  let live = [{ id: 'p', role: 'assistant', toolCalls: [{ id: 'todo' }] }]
  for (const event of sequence) live = updateToolStates(live, event)
  for (const messages of [live, messagesFromEvents(sequence)]) {
    assert.equal(messages.find(m => m.toolCalls)?.toolCalls[0].executionState, 'not_executed')
  }
  assert.equal(toolStateLabels.not_executed, '未执行')
})


test('Package and catalog runs use the same AG-UI client and keep the selected source', async t => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => 'token' } })
  t.after(() => previous ? Object.defineProperty(globalThis, 'localStorage', previous) : delete globalThis.localStorage)
  const bundle = { manifest: { entrypoint: { agent: 'main' } } }
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const body = JSON.parse(init.body)
    requests.push({ url, body })
    return new Response([
      { type: 'RUN_STARTED', threadId: body.threadId, runId: body.runId },
      { type: 'RUN_FINISHED', threadId: body.threadId, runId: body.runId },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const agent = createAguiAgent()
  await runAgui(agent, { threadId: 'package-thread', runId: 'p1', agentPackage: bundle,
    message: { id: 'm1', role: 'user', content: 'Package request' } })
  await runAgui(agent, { threadId: 'catalog-thread', runId: 'c1', agentId: 'saved-agent',
    message: { id: 'm2', role: 'user', content: 'Catalog request' } })
  assert.equal(requests[0].url, '/api/agent-package')
  assert.deepEqual(requests[0].body.agent_package, bundle)
  assert.equal(requests[1].url, '/api/agent')
  assert.equal(requests[1].body.agent_package, undefined)
  assert.equal(requests[1].body.forwardedProps.agentId, 'saved-agent')
})

test('IM notification destination is explicit per Run and never carried into the next unselected Run', async t => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => 'token' } })
  t.after(() => previous ? Object.defineProperty(globalThis, 'localStorage', previous) : delete globalThis.localStorage)
  const requests = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    const body = JSON.parse(init.body); requests.push(body)
    return new Response([
      { type: 'RUN_STARTED', threadId: body.threadId, runId: body.runId },
      { type: 'RUN_FINISHED', threadId: body.threadId, runId: body.runId },
    ].map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const agent = createAguiAgent()
  await runAgui(agent, { threadId: 'notify', runId: 'n1', notificationConnectionId: 'im_mine',
    message: { id: 'm1', role: 'user', content: 'prepare report' } })
  await runAgui(agent, { threadId: 'ordinary', runId: 'n2',
    message: { id: 'm2', role: 'user', content: 'ordinary chat' } })
  assert.equal(requests[0].notification_connection_id, 'im_mine')
  assert.equal(requests[0].forwardedProps.notification_connection_id, undefined)
  assert.equal(requests[1].notification_connection_id, undefined)
})
