import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAguiAgent } from '../src/agui/session.js'
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
