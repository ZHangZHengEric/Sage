import test from 'node:test'
import assert from 'node:assert/strict'

import {
  extractGoalPayloadFromStreamEvent,
  extractGoalTransitionFromStreamEvent,
  normalizeGoalTransition,
  normalizeSessionGoal,
} from '../goalSync.js'

test('web goal helper extracts payload from goal-carrying stream events', () => {
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
      goal_transition: { type: 'completed', objective: 'ship runtime goal contract' },
    }),
    { type: 'completed', objective: 'ship runtime goal contract' },
  )
  assert.equal(extractGoalTransitionFromStreamEvent({ type: 'assistant' }), undefined)
})

test('web goal helper normalizes session goal payloads', () => {
  assert.deepEqual(
    normalizeSessionGoal({
      objective: 'ship runtime goal contract',
      status: 'paused',
      created_at: 1,
      updated_at: 2,
      paused_reason: 'blocked',
    }),
    {
      objective: 'ship runtime goal contract',
      status: 'paused',
      created_at: 1,
      updated_at: 2,
      completed_at: null,
      paused_reason: 'blocked',
    },
  )
  assert.equal(normalizeSessionGoal(null), null)
})

test('web goal helper normalizes goal transitions and tolerates legacy payloads', () => {
  assert.deepEqual(
    normalizeGoalTransition({
      type: 'replaced',
      objective: 'ship runtime goal contract',
      previous_objective: 'draft the PR plan',
      previous_status: 'active',
    }),
    {
      type: 'replaced',
      objective: 'ship runtime goal contract',
      status: null,
      previous_objective: 'draft the PR plan',
      previous_status: 'active',
    },
  )
  assert.equal(normalizeGoalTransition(null), null)
  assert.equal(normalizeGoalTransition({}), null)
})
