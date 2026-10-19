const CLOSED = new Set([
  'sage.interaction.resolved',
  'sage.interaction.expired',
  'sage.interaction.cancelled',
])

/** Only the current Run's open question belongs in the action area. */
export function interactionAfterEvent(pending, event) {
  if (event.type === 'RUN_STARTED' || event.type === 'RUN_ERROR') return null
  if (event.type !== 'CUSTOM') return pending
  if (event.name === 'sage.interaction.requested') return event.value || null
  if (CLOSED.has(event.name)) {
    return event.value?.interaction_id === pending?.interaction_id ? null : pending
  }
  if (['sage.run.cancelled', 'sage.run.failed'].includes(event.name)) {
    const runId = event.value?.run_id
    return runId && pending?.run_id && runId !== pending.run_id ? pending : null
  }
  return pending
}
