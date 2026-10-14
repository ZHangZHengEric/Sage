import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
import { messagesFromEvents } from '../src/agui/replay.js'
import { createAguiAgent } from '../src/agui/session.js'

const events = [
  { type: 'RUN_STARTED', threadId: 'thread', runId: 'run' },
  { type: 'REASONING_MESSAGE_START', messageId: 'reason', role: 'reasoning' },
  { type: 'REASONING_MESSAGE_CONTENT', messageId: 'reason', delta: 'Thinking text' },
  { type: 'REASONING_MESSAGE_END', messageId: 'reason' },
  { type: 'TEXT_MESSAGE_START', messageId: 'empty', role: 'assistant' },
  { type: 'TEXT_MESSAGE_END', messageId: 'empty' },
  { type: 'TOOL_CALL_START', toolCallId: 'call', toolCallName: 'load_skill', parentMessageId: 'parent' },
  { type: 'TOOL_CALL_ARGS', toolCallId: 'call', delta: '{"skill":"demo"}' },
  { type: 'TOOL_CALL_END', toolCallId: 'call' },
  { type: 'TOOL_CALL_RESULT', messageId: 'result', toolCallId: 'call', content: 'Loaded' },
  { type: 'RUN_FINISHED', threadId: 'thread', runId: 'run' },
]

test('stream and history retain reasoning completion and matching tool parents', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(events.map(event =>
    `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } }))
  const snapshots = []
  const agent = createAguiAgent({ onMessages: messages => snapshots.push(structuredClone(messages)) })
  await agent.runAgent({ runId: 'run', tools: [], context: [] })
  assert.ok(snapshots.some(messages => messages.some(message => message.reasoningStreaming)))
  for (const messages of [agent.messages, messagesFromEvents(events)]) {
    assert.equal(messages.find(message => message.id === 'reason').content, 'Thinking text')
    assert.equal(messages.find(message => message.id === 'reason').reasoningStreaming, false)
    assert.equal(messages.find(message => message.id === 'parent').toolCalls[0].id, 'call')
  }
})

test('transcript joins tool results, hides empty assistants, and folds completed reasoning', async (t) => {
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { default: Transcript } = await server.ssrLoadModule('/src/components/AguiTranscript.vue')
  const messages = messagesFromEvents(events)
  const render = () => renderToString(createSSRApp(Transcript, { messages, pending: true }))
  let html = await render()
  assert.equal((html.match(/<article/g) || []).length, 2)
  assert.equal((html.match(/Loaded/g) || []).length, 1)
  assert.doesNotMatch(html, /data-role="tool"/)
  assert.doesNotMatch(html, /<details[^>]* open/)
  messages[0].reasoningStreaming = true
  html = await render()
  assert.match(html, /<details[^>]* open/)
  messages.push({ id: 'orphan', role: 'tool', toolCallId: 'missing', content: 'Standalone result' })
  html = await render()
  assert.match(html, /Standalone result/)
})
