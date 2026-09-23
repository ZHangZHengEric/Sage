const TEXT_MESSAGE_EVENTS = new Set([
  'TEXT_MESSAGE_START',
  'TEXT_MESSAGE_CONTENT',
  'TEXT_MESSAGE_END',
])
const INTERACTION_CLOSED = new Set([
  'sage.interaction.resolved',
  'sage.interaction.expired',
  'sage.interaction.cancelled',
])

/** Rebuild AG-UI Message[] from persisted protocol events. */
export function messagesFromEvents(events) {
  const messages = []
  const byId = new Map()

  for (const event of events || []) {
    switch (event.type) {
      case 'TEXT_MESSAGE_START': {
        const message = {
          id: event.messageId,
          role: event.role || 'assistant',
          content: '',
        }
        byId.set(event.messageId, message)
        messages.push(message)
        break
      }
      case 'TEXT_MESSAGE_CONTENT': {
        const message = byId.get(event.messageId)
        if (message) {
          message.content = `${message.content || ''}${event.delta || ''}`
        } else {
          const created = {
            id: event.messageId,
            role: 'assistant',
            content: event.delta || '',
          }
          byId.set(event.messageId, created)
          messages.push(created)
        }
        break
      }
      case 'TOOL_CALL_START': {
        const parent =
          [...messages].reverse().find((item) => item.role === 'assistant') || {
            id: event.toolCallId,
            role: 'assistant',
            content: '',
            toolCalls: [],
          }
        if (!messages.includes(parent)) messages.push(parent)
        const call = {
          id: event.toolCallId,
          type: 'function',
          function: { name: event.toolCallName || 'tool', arguments: '' },
        }
        parent.toolCalls = [...(parent.toolCalls || []), call]
        byId.set(event.toolCallId, call)
        break
      }
      case 'TOOL_CALL_ARGS': {
        const call = byId.get(event.toolCallId)
        if (call?.function) {
          call.function.arguments += event.delta || ''
        }
        break
      }
      case 'TOOL_CALL_RESULT': {
        messages.push({
          id: event.messageId || event.toolCallId,
          role: 'tool',
          content: event.content || '',
          toolCallId: event.toolCallId,
        })
        break
      }
      case 'REASONING_MESSAGE_CONTENT': {
        const id = event.messageId || 'reasoning'
        const existing = byId.get(id)
        if (existing) {
          existing.content += event.delta || ''
        } else {
          const created = { id, role: 'reasoning', content: event.delta || '' }
          byId.set(id, created)
          messages.push(created)
        }
        break
      }
      default:
        break
    }
  }
  return messages
}

/** The question this thread is still waiting on, or null when it is not.
 *
 * A request stays open until its own resolution says otherwise, so the scan
 * matches ids rather than assuming the latest close belongs to the latest
 * question.
 */
export function pendingInteraction(events) {
  let pending = null
  for (const event of events || []) {
    if (event.type !== 'CUSTOM') continue
    if (event.name === 'sage.interaction.requested') {
      pending = event.value || null
    } else if (
      INTERACTION_CLOSED.has(event.name) &&
      event.value?.interaction_id === pending?.interaction_id
    ) {
      pending = null
    }
  }
  return pending
}

/** Messages as they stood when the thread's most recent Run began.
 *
 * Answering a suspended Run replays it from its first event so the client
 * rebuilds item state exactly, which means everything that Run has already
 * shown arrives a second time. Rewinding to here is what keeps that replay
 * from appending to text already on screen. The Run's own user message is
 * kept: the server never replays inbound user text, because the client owns
 * it. Returns null when the page does not reach back to a Run boundary, so
 * the caller can decline to rewind rather than blank the transcript.
 */
export function messagesBeforeLastRun(events) {
  const list = events || []
  const start = list.findLastIndex((event) => event.type === 'RUN_STARTED')
  if (start < 0) return null
  const owned = new Set()
  const kept = list.slice(0, start)
  for (const event of list.slice(start)) {
    if (event.type === 'TEXT_MESSAGE_START' && event.role === 'user') {
      owned.add(event.messageId)
    }
    if (TEXT_MESSAGE_EVENTS.has(event.type) && owned.has(event.messageId)) {
      kept.push(event)
    }
  }
  return messagesFromEvents(kept)
}
