import { describe, expect, it } from 'vitest'

import {
  extractGoalPayloadFromStreamEvent,
  extractGoalTransitionFromStreamEvent,
  normalizeGoalTransition,
  normalizeSessionGoal,
} from '../goalSync.js'

describe('web goalSync helpers', () => {
  it('extracts payload from goal-carrying stream events', () => {
    expect(
    extractGoalPayloadFromStreamEvent({
      type: 'tool_result',
      goal: { objective: 'ship runtime goal contract', status: 'completed' },
    }),
    ).toEqual({ objective: 'ship runtime goal contract', status: 'completed' })
    expect(extractGoalPayloadFromStreamEvent({ type: 'assistant', content: 'done' })).toBeUndefined()
    expect(extractGoalPayloadFromStreamEvent({ type: 'stream_end', goal: null })).toBeNull()
    expect(
      extractGoalTransitionFromStreamEvent({
        type: 'stream_end',
        goal_transition: { type: 'completed', objective: 'ship runtime goal contract' },
      }),
    ).toEqual({ type: 'completed', objective: 'ship runtime goal contract' })
    expect(extractGoalTransitionFromStreamEvent({ type: 'assistant' })).toBeUndefined()
  })

  it('normalizes session goal payloads', () => {
    expect(
      normalizeSessionGoal({
        objective: 'ship runtime goal contract',
        status: 'paused',
        created_at: 1,
        updated_at: 2,
        paused_reason: 'blocked',
      }),
    ).toEqual({
      objective: 'ship runtime goal contract',
      status: 'paused',
      created_at: 1,
      updated_at: 2,
      completed_at: null,
      paused_reason: 'blocked',
    })
    expect(normalizeSessionGoal(null)).toBeNull()
  })

  it('normalizes goal transitions and tolerates legacy payloads', () => {
    expect(
      normalizeGoalTransition({
        type: 'replaced',
        objective: 'ship runtime goal contract',
        previous_objective: 'draft the PR plan',
        previous_status: 'active',
      }),
    ).toEqual({
      type: 'replaced',
      objective: 'ship runtime goal contract',
      status: null,
      previous_objective: 'draft the PR plan',
      previous_status: 'active',
    })
    expect(normalizeGoalTransition(null)).toBeNull()
    expect(normalizeGoalTransition({})).toBeNull()
  })
})
