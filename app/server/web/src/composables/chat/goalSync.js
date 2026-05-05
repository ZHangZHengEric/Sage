export const extractGoalPayloadFromStreamEvent = (data) => {
  if (!data || typeof data !== 'object' || !Object.prototype.hasOwnProperty.call(data, 'goal')) {
    return undefined
  }
  return data.goal || null
}

export const extractGoalTransitionFromStreamEvent = (data) => {
  if (!data || typeof data !== 'object' || !Object.prototype.hasOwnProperty.call(data, 'goal_transition')) {
    return undefined
  }
  return data.goal_transition || null
}

export const normalizeSessionGoal = (goal) => {
  if (!goal) return null
  return {
    objective: goal.objective,
    status: goal.status,
    created_at: goal.created_at,
    updated_at: goal.updated_at,
    completed_at: goal.completed_at || null,
    paused_reason: goal.paused_reason || null
  }
}

export const normalizeGoalTransition = (transition) => {
  if (!transition || typeof transition !== 'object') return null
  const transitionType = String(transition.type || '').trim()
  if (!transitionType) return null
  return {
    type: transitionType,
    objective: transition.objective || null,
    status: transition.status || null,
    previous_objective: transition.previous_objective || null,
    previous_status: transition.previous_status || null
  }
}
