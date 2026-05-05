import test from 'node:test'
import assert from 'node:assert/strict'

import {
  extractGoalPayloadFromStreamEvent,
  extractGoalTransitionFromStreamEvent,
  normalizeGoalTransition,
  normalizeSessionGoal,
} from '../goalSync.js'

test('desktop goal helper extracts payload from goal-carrying stream events', () => {
  assert.deepEqual(
    extractGoalPayloadFromStreamEvent({
      type: 'tool_result',
      goal: { objective: 'ship runtime goal contract', status: 'completed' },
    }),
    { objective: 'ship runtime goal contract', status: 'completed' },
  )
  assert.equal(
    extractGoalPayloadFromStreamEvent({ type: 'assistant', content: 'done' }),
    undefined,
  )
  assert.equal(
    extractGoalPayloadFromStreamEvent({ type: 'stream_end', goal: null }),
    null,
  )
  assert.deepEqual(
    extractGoalTransitionFromStreamEvent({
      type: 'stream_end',
      goal_transition: { type: 'cleared', previous_objective: 'ship runtime goal contract' },
    }),
    { type: 'cleared', previous_objective: 'ship runtime goal contract' },
  )
  assert.equal(extractGoalTransitionFromStreamEvent({ type: 'assistant' }), undefined)
})

test('desktop goal helper normalizes session goal payloads', () => {
  assert.deepEqual(
    normalizeSessionGoal({
      objective: 'ship runtime goal contract',
      status: 'active',
      created_at: 1,
      updated_at: 2,
      completed_at: 3,
    }),
    {
      objective: 'ship runtime goal contract',
      status: 'active',
      created_at: 1,
      updated_at: 2,
      completed_at: 3,
      paused_reason: null,
    },
  )
  assert.equal(normalizeSessionGoal(undefined), null)
})

test('desktop goal helper normalizes goal transitions and tolerates legacy payloads', () => {
  assert.deepEqual(
    normalizeGoalTransition({
      type: 'resumed',
      objective: 'ship runtime goal contract',
    }),
    {
      type: 'resumed',
      objective: 'ship runtime goal contract',
      status: null,
      previous_objective: null,
      previous_status: null,
    },
  )
  assert.equal(normalizeGoalTransition(null), null)
  assert.equal(normalizeGoalTransition({}), null)
})
