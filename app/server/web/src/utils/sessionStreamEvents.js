export const isCurrentSessionStreamEnd = (data, sessionId) =>
  data?.type === 'stream_end' && data?.session_id === sessionId

export const getSessionMessageIndexKey = (message = {}, fallbackSessionId = '') => {
  const messageId = message?.message_id
  if (!messageId) return null
  const sessionId = message?.session_id || fallbackSessionId || ''
  return `${sessionId}::${messageId}`
}
