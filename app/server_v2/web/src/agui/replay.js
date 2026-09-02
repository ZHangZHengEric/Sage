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
