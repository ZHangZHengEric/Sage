// Protocol call frames describe model output; only execution events mean running.
const states = {
  proposed: 'queued', awaiting_approval: 'awaiting_approval', dispatching: 'queued',
  started: 'running', succeeded: 'completed', failed: 'failed',
  cancelled: 'cancelled', unknown: 'unknown', reconciling: 'reconciling',
}
const terminal = new Set(['completed', 'failed', 'denied', 'cancelled', 'incomplete', 'not_executed'])

export function toolState(call, hasResult = false) {
  return call.executionState || (hasResult ? 'completed' : 'preparing')
}

export const toolStateLabels = {
  preparing: '准备调用', queued: '待执行', awaiting_approval: '待审批',
  not_executed: '未执行', running: '执行中', completed: '已完成', failed: '失败', denied: '已拒绝',
  cancelled: '已取消', unknown: '结果待确认', reconciling: '核对结果中', incomplete: '未执行完毕',
}

export function updateToolStates(messages, event) {
  let id = event.toolCallId
  let state
  if (event.type === 'TOOL_CALL_END') state = 'queued'
  if (event.type === 'TOOL_CALL_RESULT') state = 'completed'
  if (event.type === 'CUSTOM' && event.name?.startsWith('tool.call.')) {
    id = event.value?.tool_call_id
    state = states[event.name.slice('tool.call.'.length)]
    if (event.name === 'tool.call.reconciled') {
      state = event.value?.error ? 'failed' : event.value?.state === 'completed' ? 'completed' : 'unknown'
    }
    if (event.value?.error?.code === 'tool.policy_denied') state = 'denied'
    if (event.value?.error?.metadata?.side_effect_state === 'not_applied') state = 'not_executed'
  }
  const runEnded = event.type === 'CUSTOM' && ['sage.run.cancelled', 'sage.run.failed'].includes(event.name)
  if ((!id || !state) && !runEnded) return messages
  return messages.map(message => !message.toolCalls ? message : {
    ...message,
    toolCalls: message.toolCalls.map(call => {
      if (runEnded && !terminal.has(call.executionState)) {
        return { ...call, executionState: event.name === 'sage.run.cancelled' ? 'cancelled' : 'incomplete' }
      }
      if (call.id !== id) return call
      // A result frame carries text only; never overwrite a failure/denial event.
      if (event.type === 'TOOL_CALL_RESULT' && terminal.has(call.executionState)) return call
      return { ...call, executionState: state }
    }),
  })
}
