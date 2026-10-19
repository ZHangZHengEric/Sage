import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pendingInteraction } from '../src/agui/replay.js'
import { createAguiAgent } from '../src/agui/session.js'

const question = { interaction_id: 'old-question', run_id: 'old', interaction_type: 'approval' }
const start = runId => ({ type: 'RUN_STARTED', threadId: 'thread', runId })
const request = value => ({ type: 'CUSTOM', name: 'sage.interaction.requested', value })
const custom = (name, value = {}) => ({ type: 'CUSTOM', name, value })

test('cancelled historical approval disappears without an interaction id on the cancellation', () => {
  const events = [start('old'), request(question), custom('sage.run.suspended'),
    custom('sage.run.cancelled', { state: 'cancelled' }), start('new')]
  assert.equal(pendingInteraction(events.slice(0, -1)), null)
  assert.equal(pendingInteraction(events), null)
})

test('new work and failed runs retire an old question; a suspended stream keeps it', () => {
  const events = [start('old'), request(question), custom('sage.run.suspended'),
    { type: 'RUN_FINISHED', threadId: 'thread', runId: 'old' }]
  assert.deepEqual(pendingInteraction(events), question)
  assert.equal(pendingInteraction([...events, start('new')]), null)
  assert.equal(pendingInteraction([...events, { type: 'RUN_ERROR', message: 'failed' }]), null)
})

test('late close events for another question or run leave the current approval intact', () => {
  const current = { ...question, interaction_id: 'new-question', run_id: 'new' }
  const events = [start('new'), request(current),
    custom('sage.interaction.resolved', { interaction_id: question.interaction_id }),
    custom('sage.run.cancelled', { run_id: 'old' })]
  assert.deepEqual(pendingInteraction(events), current)
  assert.equal(pendingInteraction([...events,
    custom('sage.interaction.cancelled', { interaction_id: current.interaction_id })]), null)
})

test('live updates and history agree when a cancelled run is followed by new work', async t => {
  const events = [start('old'), request(question), custom('sage.run.cancelled', { state: 'cancelled' }),
    { type: 'RUN_FINISHED', threadId: 'thread', runId: 'old' }]
  t.mock.method(globalThis, 'fetch', async () => new Response(events.map(event =>
    `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } }))
  const shown = []
  const agent = createAguiAgent({ onInteraction: value => shown.push(value) })
  await agent.runAgent({ runId: 'old', tools: [], context: [] })
  assert.ok(shown.some(value => value?.interaction_id === question.interaction_id))
  assert.equal(shown.at(-1), pendingInteraction(events))
})

test('live new Run start clears an earlier question even without its close event', async t => {
  let next = [start('old'), request(question), custom('sage.run.suspended'),
    { type: 'RUN_FINISHED', threadId: 'thread', runId: 'old' }]
  t.mock.method(globalThis, 'fetch', async () => new Response(next.map(event =>
    `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } }))
  const shown = []
  const agent = createAguiAgent({ onInteraction: value => shown.push(value) })
  await agent.runAgent({ runId: 'old', tools: [], context: [] })
  assert.deepEqual(shown.at(-1), question)
  next = [start('new'), { type: 'RUN_FINISHED', threadId: 'thread', runId: 'new' }]
  await agent.runAgent({ runId: 'new', tools: [], context: [] })
  assert.equal(shown.at(-1), null)
})
