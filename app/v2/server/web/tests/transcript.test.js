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

test('history keeps reasoning before an answer started before the first reasoning delta', async (t) => {
  const sequence = [
    { type: 'RUN_STARTED', threadId: 'thread', runId: 'run' },
    { type: 'REASONING_START', messageId: 'reason' },
    { type: 'REASONING_MESSAGE_START', messageId: 'reason', role: 'reasoning' },
    { type: 'TEXT_MESSAGE_START', messageId: 'answer', role: 'assistant' },
    { type: 'REASONING_MESSAGE_CONTENT', messageId: 'reason', delta: 'Thinking first' },
    { type: 'REASONING_MESSAGE_END', messageId: 'reason' },
    { type: 'REASONING_END', messageId: 'reason' },
    { type: 'TEXT_MESSAGE_CONTENT', messageId: 'answer', delta: 'Answer second' },
    { type: 'TEXT_MESSAGE_END', messageId: 'answer' },
    { type: 'RUN_FINISHED', threadId: 'thread', runId: 'run' },
  ]
  t.mock.method(globalThis, 'fetch', async () => new Response(sequence.map(event =>
    `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } }))
  const agent = createAguiAgent()
  await agent.runAgent({ runId: 'run', tools: [], context: [] })
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { default: Transcript } = await server.ssrLoadModule('/src/components/AguiTranscript.vue')
  for (const messages of [agent.messages, messagesFromEvents(sequence)]) {
    assert.deepEqual(messages.map(message => message.id), ['reason', 'answer'])
    assert.equal(messages[0].content, 'Thinking first')
    assert.equal(messages[0].reasoningStreaming, false)
    const html = await renderToString(createSSRApp(Transcript, { messages }))
    assert.ok(html.indexOf('Thinking first') < html.indexOf('Answer second'))
    assert.doesNotMatch(html, /<details[^>]* open/)
  }
})

test('process-only messages have no avatar or empty text, and copy actions belong to the last reply of each turn', async (t) => {
  const server = await createServer({ optimizeDeps: { noDiscovery: true, entries: [] }, server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { default: Transcript } = await server.ssrLoadModule('/src/components/AguiTranscript.vue')
  const tool = id => ({ id, role: 'assistant', content: '', toolCalls: [{ id: `call-${id}`, function: { name: 'load_skill', arguments: '{}' }, executionState: 'completed' }] })
  const messages = [
    { id: 'q1', role: 'user', content: '第一个问题' },
    { id: 'intro', role: 'assistant', content: '先加载分析工具。' },
    tool('first'),
    { id: 'reason', role: 'reasoning', content: '分析中', reasoningStreaming: false },
    tool('second'),
    { id: 'answer1', role: 'assistant', content: '第一轮结论' },
    { id: 'q2', role: 'user', content: '第二个问题' },
    { id: 'answer2', role: 'assistant', content: '第二轮结论' },
  ]
  const html = await renderToString(createSSRApp(Transcript, { messages }))
  assert.equal((html.match(/class="msg-avatar"/g) || []).length, 3)
  assert.equal((html.match(/复制回复/g) || []).length, 2)
  assert.doesNotMatch(html.slice(0, html.indexOf('第一轮结论')), /复制回复/)
  assert.doesNotMatch(html, /<p class="plain"><\/p>/)
  assert.equal((html.match(/aria-label="工具调用"/g) || []).length, 2)
  assert.doesNotMatch(html, /<header><svg[^]*?<span>工具调用<\/span>/)
  const streaming = await renderToString(createSSRApp(Transcript, { messages, pending: true }))
  assert.doesNotMatch(streaming, /复制回复/)
})

test('JSON tool results remain strings and render in both stream and history', async (t) => {
  const content = JSON.stringify({ status: 'success', message: '写入成功', count: 0 })
  const structuredEvents = events.map(event => event.type === 'TOOL_CALL_RESULT'
    ? { ...event, content } : event)
  t.mock.method(globalThis, 'fetch', async () => new Response(structuredEvents.map(event =>
    `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } }))
  const agent = createAguiAgent()
  await agent.runAgent({ runId: 'run', tools: [], context: [] })
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { default: Transcript } = await server.ssrLoadModule('/src/components/AguiTranscript.vue')
  for (const messages of [agent.messages, messagesFromEvents(structuredEvents)]) {
    assert.equal(messages.find(message => message.role === 'tool').content, content)
    const html = await renderToString(createSSRApp(Transcript, { messages }))
    assert.equal((html.match(/写入成功/g) || []).length, 1)
    assert.doesNotMatch(html, /data-role="tool"/)
  }
})

test('tool execution states agree in live streams and history, including approval and denial', async (t) => {
  const custom = (name, id, extra = {}) => ({ type: 'CUSTOM', name, value: { tool_call_id: id, ...extra } })
  const frames = id => [
    { type: 'TOOL_CALL_START', toolCallId: id, toolCallName: id, parentMessageId: `p-${id}` },
    { type: 'TOOL_CALL_ARGS', toolCallId: id, delta: '{}' },
    { type: 'TOOL_CALL_END', toolCallId: id },
  ]
  let sequence = [events[0], ...frames('load_skill'), ...frames('list_dir'),
    custom('tool.call.awaiting_approval', 'load_skill'), custom('sage.run.suspended'), events.at(-1)]
  t.mock.method(globalThis, 'fetch', async () => new Response(sequence.map(event =>
    `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } }))
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  const { default: Transcript } = await server.ssrLoadModule('/src/components/AguiTranscript.vue')
  const agent = createAguiAgent()
  await agent.runAgent({ runId: 'run', tools: [], context: [] })
  for (const messages of [agent.messages, messagesFromEvents(sequence)]) {
    assert.deepEqual(messages.flatMap(m => m.toolCalls || []).map(c => c.executionState), ['awaiting_approval', 'queued'])
    const html = await renderToString(createSSRApp(Transcript, { messages, pending: true, interaction: { interaction_type: 'approval' } }))
    assert.match(html, /待审批/)
    assert.match(html, /待执行/)
    assert.match(html, /等待审批/)
    assert.doesNotMatch(html, /执行中|正在生成|tool-spinner/)
  }
  sequence.splice(-1, 1,
    custom('tool.call.started', 'load_skill'),
    custom('tool.call.failed', 'load_skill', { error: { code: 'skill.not_found' } }),
    { type: 'TOOL_CALL_RESULT', messageId: 'r1', toolCallId: 'load_skill', content: 'Missing' },
    custom('tool.call.cancelled', 'list_dir', { error: { code: 'tool.policy_denied' } }),
    { type: 'TOOL_CALL_RESULT', messageId: 'r2', toolCallId: 'list_dir', content: 'Denied' }, events.at(-1))
  const snapshots = []
  const resumed = createAguiAgent({ onMessages: m => snapshots.push(structuredClone(m)) })
  await resumed.runAgent({ runId: 'run', tools: [], context: [] })
  assert.ok(snapshots.some(m => m.some(m => m.toolCalls?.some(c => c.executionState === 'running'))))
  for (const messages of [resumed.messages, messagesFromEvents(sequence)]) {
    assert.deepEqual(messages.flatMap(m => m.toolCalls || []).map(c => c.executionState), ['failed', 'denied'])
  }
})
