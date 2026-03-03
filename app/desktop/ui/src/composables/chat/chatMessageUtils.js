export const injectFirstUserMessageIfNeeded = (allMessages, sessionId, activeMeta) => {
  if (activeMeta?.status !== 'running' || !activeMeta?.user_input) return allMessages
  const pendingMessageId = `pending_user_${sessionId}`
  const baseMessages = allMessages.filter(msg => msg.message_id !== pendingMessageId)
  const normalizedInput = String(activeMeta.user_input || '').trim()
  const lastSessionMessageIndex = (() => {
    for (let i = baseMessages.length - 1; i >= 0; i--) {
      if (baseMessages[i]?.session_id === sessionId) return i
    }
    return -1
  })()
  if (lastSessionMessageIndex >= 0) {
    const lastSessionMessage = baseMessages[lastSessionMessageIndex]
    const isSameUserInput =
      lastSessionMessage?.role === 'user' &&
      String(lastSessionMessage?.content || '').trim() === normalizedInput
    if (isSameUserInput) return baseMessages
  }
  if (!normalizedInput) return baseMessages
  const pendingUserMessage = {
    role: 'user',
    content: normalizedInput,
    message_id: pendingMessageId,
    type: 'USER',
    session_id: sessionId,
    timestamp: Date.now()
  }
  if (lastSessionMessageIndex === -1) {
    return [pendingUserMessage, ...baseMessages]
  }
  return [
    ...baseMessages.slice(0, lastSessionMessageIndex + 1),
    pendingUserMessage,
    ...baseMessages.slice(lastSessionMessageIndex + 1)
  ]
}
