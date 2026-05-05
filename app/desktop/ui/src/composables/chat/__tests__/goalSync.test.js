import { describe, expect, it } from 'vitest'

import {
  extractGoalPayloadFromStreamEvent,
  extractGoalTransitionFromStreamEvent,
  normalizeGoalTransition,
  normalizeSessionGoal,
} from '../goalSync.js'

describe('desktop goalSync helpers', () => {
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
        goal_transition: { type: 'cleared', previous_objective: 'ship runtime goal contract' },
      }),
    ).toEqual({ type: 'cleared', previous_objective: 'ship runtime goal contract' })
    expect(extractGoalTransitionFromStreamEvent({ type: 'assistant' })).toBeUndefined()
  })

  it('normalizes session goal payloads', () => {
    expect(
      normalizeSessionGoal({
        objective: 'ship runtime goal contract',
        status: 'active',
        created_at: 1,
        updated_at: 2,
        completed_at: 3,
      }),
    ).toEqual({
      objective: 'ship runtime goal contract',
      status: 'active',
      created_at: 1,
      updated_at: 2,
      completed_at: 3,
      paused_reason: null,
    })
    expect(normalizeSessionGoal(undefined)).toBeNull()
  })

  it('normalizes goal transitions and tolerates legacy payloads', () => {
    expect(
      normalizeGoalTransition({
        type: 'resumed',
        objective: 'ship runtime goal contract',
      }),
    ).toEqual({
      type: 'resumed',
      objective: 'ship runtime goal contract',
      status: null,
      previous_objective: null,
      previous_status: null,
    })
    expect(normalizeGoalTransition(null)).toBeNull()
    expect(normalizeGoalTransition({})).toBeNull()
  })
})
