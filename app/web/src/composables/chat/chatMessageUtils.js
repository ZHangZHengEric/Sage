export const mergeMessageList = (currentMessages, messageData) => {
  if (messageData.type === 'stream_end') return currentMessages
  const nextMessages = [...currentMessages]
  const messageId = messageData.message_id
  const existingIndex = nextMessages.findIndex(msg => msg.message_id === messageId)
  if (existingIndex >= 0) {
    const existing = nextMessages[existingIndex]
    if (messageData.role === 'tool' || messageData.message_type === 'tool_call_result') {
      nextMessages[existingIndex] = {
        ...messageData,
        timestamp: messageData.timestamp || Date.now()
      }
    } else {
      nextMessages[existingIndex] = {
        ...existing,
        ...messageData,
        content: (existing.content || '') + (messageData.content || ''),
        timestamp: messageData.timestamp || Date.now()
      }
    }
  } else {
    nextMessages.push({
      ...messageData,
      timestamp: messageData.timestamp || Date.now()
    })
  }
  return nextMessages
}
