import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRenderer, createSSRApp, h, nextTick, reactive, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'
import { interactionCallId, resultFile, transcriptMessages, rememberDescription, decisionErrorText } from '../src/agui/presentation.js'
import { renderMessageMarkdown } from '../src/agui/markdown.js'
const call = (id, args = '{"file_path":"notes/week.md","mode":"overwrite"}') => ({ id, function: { name: 'file_write', arguments: args }, executionState: 'awaiting_approval' })
const question = { interaction_id: 'ask', interaction_type: 'approval', allowed_decisions: ['approve_once', 'deny', 'approve_and_remember', 'cancel'], payload: { tool_name: 'file_write', arguments: { mode: 'overwrite', file_path: 'notes/week.md' }, side_effect_level: 'write', approval_scopes: ['session'] } }
async function component(t, name) {
  const server = await createServer({ server: { middlewareMode: true, watch: null, hmr: false, ws: false } })
  t.after(() => server.close())
  return (await server.ssrLoadModule(`/src/components/${name}.vue`)).default
}

test('approval association is exact and refuses ambiguous or unrelated pending calls', () => {
  const messages = [{ id: 'm', role: 'assistant', toolCalls: [call('a'), call('b', '{"file_path":"other.md"}')] }]
  assert.equal(interactionCallId(messages, question), 'a')
  assert.equal(interactionCallId(messages, { ...question, payload: { ...question.payload, tool_call_id: 'missing' } }), '')
  assert.equal(interactionCallId([...messages, { toolCalls: [call('same')] }], question), '')
  assert.equal(interactionCallId(messages, { ...question, interaction_type: 'user_input' }), '')
  assert.equal(interactionCallId(messages, { ...question, payload: { ...question.payload, tool_name: 'other' } }), '')
  assert.equal(interactionCallId(messages, { ...question, payload: { ...question.payload, arguments: 'incomplete {' } }), '')
})

test('presentation joins only adjacent empty tool parents and never mutates protocol messages', () => {
  const source = [{ id: 'a', role: 'assistant', content: '', toolCalls: [call('one')] }, { id: 'result', role: 'tool', toolCallId: 'one', content: 'output' }, { id: 'b', role: 'assistant', content: '', toolCalls: [call('two')] }, { id: 'text', role: 'assistant', content: '结论' }, { id: 'c', role: 'assistant', content: '', toolCalls: [call('three')] }, { id: 'orphan', role: 'tool', toolCallId: 'missing', content: 'orphan output' }]
  const before = structuredClone(source), visible = transcriptMessages(source)
  assert.deepEqual(visible.map(item => item.id), ['a', 'text', 'c', 'orphan'])
  assert.deepEqual(visible[0].toolCalls.map(item => item.id), ['one', 'two'])
  assert.deepEqual(source, before)
  const result = { content: '{"status":"success","file_path":"notes/week.md"}' }
  assert.equal(resultFile({ ...call('a'), executionState: 'completed' }, result), 'notes/week.md')
  for (const executionState of ['denied', 'unknown', 'failed', 'not_executed']) assert.equal(resultFile({ ...call('a'), executionState }, result), '')
  assert.match(rememberDescription(question.payload), /仅在本会话/)
  assert.doesNotMatch(rememberDescription({}), /仅在本会话|永久/)
  assert.equal(decisionErrorText(new Error('HTTP 503: {"message":"提交失败，请重试"}')), '提交失败，请重试')
})

test('message Markdown preserves code and tables while escaping active HTML and unsafe URLs', () => {
  const html = renderMessageMarkdown('```html\n<img src=x onerror=alert(1)>\n```\n\n| 项目 | 状态 |\n| --- | --- |\n| A | 完成 |\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n[y](java&#x73;cript:alert(1))\n\n[资料](https://example.test/path)')
  assert.match(html, /data-copy-code/)
  assert.match(html, /message-table/)
  assert.match(html, /&lt;img/)
  assert.doesNotMatch(html, /<img|href="javascript:|href="java&#/i)
  assert.match(html, /rel="noopener noreferrer"/)
})

test('a pending decision renders once next to its exact call and remains visible in read-only fallback', async t => {
  const Transcript = await component(t, 'AguiTranscript')
  const messages = [{ id: 'm', role: 'assistant', toolCalls: [call('a')] }]
  let html = await renderToString(createSSRApp(Transcript, { messages, interaction: question }))
  assert.equal((html.match(/data-active-interaction/g) || []).length, 1)
  assert.equal((html.match(/<h2>允许运行 file_write 吗/g) || []).length, 1)
  assert.match(html, /更多操作/)
  assert.match(html, /查看完整调用参数/)
  html = await renderToString(createSSRApp(Transcript, { messages: [], interaction: question, readOnly: true }))
  assert.equal((html.match(/data-active-interaction/g) || []).length, 1)
  assert.match(html, /等待会话所属用户处理/)
  assert.doesNotMatch(html, /允许这一次|允许并记住|拒绝这次调用/)
})

test('failed tool defaults to its error output and preserves unknown source names', async t => {
  const Card = await component(t, 'ToolCallCard')
  const html = await renderToString(createSSRApp(Card, { call: { ...call('a'), executionState: 'failed' }, result: { content: '{"error":"真实错误"}' } }))
  assert.match(html, /<details[^>]*open/)
  assert.match(html, /输出 · 错误/)
  assert.match(html, /真实错误/)
  assert.match(html, /file_write/)
  assert.doesNotMatch(html, /写入文件/)
})

test('interaction permits only offered decisions, requires answers only for text decisions, and blocks busy or read-only writes', async t => {
  const Prompt = await component(t, 'InteractionPrompt')
  const props = reactive({ interaction: { interaction_type: 'user_input', allowed_decisions: ['submit', 'cancel'], payload: {} }, answer: '', busy: false, readOnly: false })
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const decisions = [], RenderPrompt = { ...Prompt, render: () => null }
  const app = renderer.createApp({ render: () => h(RenderPrompt, { ...props, onDecide: value => decisions.push(value) }) })
  app.provide(ssrContextKey, {})
  const vm = app.mount({}); t.after(() => app.unmount())
  const child = vm.$.subTree.component, state = child.setupState
  state.choose('approve_once'); state.choose('submit')
  assert.equal(decisions.length, 0)
  state.choose('cancel')
  assert.deepEqual(decisions[0], { decision: 'cancel', payload: {} })
  props.answer = '  给同事看  '; await nextTick(); state.choose('submit')
  assert.deepEqual(decisions[1], { decision: 'submit', payload: { text: '给同事看' } })
  props.busy = true; await nextTick(); state.choose('submit')
  props.busy = false; props.readOnly = true; await nextTick(); state.choose('cancel')
  assert.equal(decisions.length, 2)
})
