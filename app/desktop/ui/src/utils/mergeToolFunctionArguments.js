/**
 * Align with sagents/agent_base._handle_tool_calls_chunk and stream_merger.merge_chat_completion_chunks:
 * - tool function arguments are streamed as string fragments concatenated with +=
 * - fibre backend_client merges same id by appending when existing arguments is truthy
 * - never clobber accumulated JSON string with an empty object {}
 */
export function mergeToolFunctionArguments (existingArgs, incomingArgs) {
  if (incomingArgs === undefined) {
    return existingArgs
  }
  if (incomingArgs === null) {
    return existingArgs !== undefined ? existingArgs : incomingArgs
  }
  if (incomingArgs === '') {
    return existingArgs !== undefined && existingArgs !== null ? existingArgs : incomingArgs
  }

  if (typeof incomingArgs === 'object' && !Array.isArray(incomingArgs)) {
    if (Object.keys(incomingArgs).length === 0) {
      return existingArgs !== undefined && existingArgs !== null ? existingArgs : incomingArgs
    }
    return incomingArgs
  }

  if (typeof incomingArgs === 'string') {
    if (typeof existingArgs === 'object' && existingArgs !== null && !Array.isArray(existingArgs)) {
      if (Object.keys(existingArgs).length > 0) {
        return existingArgs
      }
    }
    const existingText = typeof existingArgs === 'string' ? existingArgs : ''
    const incomingText = incomingArgs
    if (!existingText) return incomingText
    if (!incomingText) return existingText
    if (incomingText.startsWith(existingText)) return incomingText
    if (existingText.startsWith(incomingText)) return existingText
    return `${existingText}${incomingText}`
  }

  return incomingArgs
}
