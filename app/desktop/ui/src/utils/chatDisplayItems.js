import { isToolResultMessage, isTokenUsageMessage } from '@/utils/messageLabels.js'

export const CHAT_DISPLAY_MODES = {
  EXECUTION: 'execution',
  DELIVERY: 'delivery'
}

const RETAINED_ASSISTANT_EXCLUDED_TYPES = new Set(['token_usage', 'reasoning_content', 'task_analysis'])
const TOOL_ACTION_CODES = {
  inspect_info: 'inspect_info',
  edit_files: 'edit_files',
  run_commands: 'run_commands',
  delegate_tasks: 'delegate_tasks',
  create_agents: 'create_agents',
  manage_tasks: 'manage_tasks',
  collect_input: 'collect_input',
  generate_assets: 'generate_assets',
  use_tools: 'use_tools',
  process_updates: 'process_updates'
}

const toTimestampMs = (value) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return num < 10000000000 ? num * 1000 : num
}

const hasToolCalls = (message) => Array.isArray(message?.tool_calls) && message.tool_calls.length > 0

const isToolRelatedMessage = (message) => hasToolCalls(message) || isToolResultMessage(message)

const getTextContent = (content) => {
  if (!content) return ''
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .filter(item => item?.type === 'text' && typeof item.text === 'string')
    .map(item => item.text)
    .join('\n')
}

const getImageUrls = (content) => {
  if (!Array.isArray(content)) return []
  return content
    .filter(item => item?.type === 'image_url' && item.image_url?.url)
    .map(item => item.image_url.url)
}

const hasVisibleContent = (message) => {
  const text = getTextContent(message?.content)
  const images = getImageUrls(message?.content)
  return text.trim().length > 0 || images.length > 0
}

const parseJsonSafely = (value) => {
  if (!value) return null
  if (typeof value === 'object') return value
  if (typeof value !== 'string') return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

const toDisplayText = (value) => {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const buildToolResultMap = (messages) => {
  const resultMap = new Map()
  messages.forEach((message) => {
    if (!isToolResultMessage(message) || !message?.tool_call_id) return
    resultMap.set(message.tool_call_id, message)
  })
  return resultMap
}

const extractFinishTaskContent = (toolCall, toolResult) => {
  const args = parseJsonSafely(toolCall?.function?.arguments) || {}
  const candidates = [
    args.result,
    args.content,
    args.message,
    toolResult?.content,
    toolResult?.message
  ]

  for (const candidate of candidates) {
    const text = toDisplayText(candidate)
    if (text) {
      return {
        content: text,
        status: args.status || toolResult?.status || null
      }
    }
  }

  const status = args.status || toolResult?.status || null
  if (status) {
    return {
      content: toDisplayText(status),
      status
    }
  }

  return null
}

const createFinishTaskMessage = (message, toolCall, toolResult) => {
  const extracted = extractFinishTaskContent(toolCall, toolResult)
  if (!extracted?.content) return null

  return {
    ...message,
    message_id: `${message.message_id || 'message'}:finish:${toolCall.id || 'tool'}`,
    tool_calls: undefined,
    role: 'assistant',
    type: 'finish_task_content',
    message_type: 'finish_task_content',
    content: extracted.content,
    metadata: {
      ...(message.metadata || {}),
      finish_task: {
        status: extracted.status,
        tool_call_id: toolCall.id || null,
        source_message_id: message.message_id || null
      }
    }
  }
}

const createPendingFinishTaskMessage = (message, toolCall) => ({
  ...message,
  message_id: `${message.message_id || 'message'}:finish:pending:${toolCall.id || 'tool'}`,
  role: 'assistant',
  tool_calls: [toolCall],
  metadata: {
    ...(message.metadata || {}),
    finish_task: {
      status: 'pending',
      tool_call_id: toolCall.id || null,
      source_message_id: message.message_id || null
    }
  }
})

export const normalizeChatMessages = (messages = []) => {
  const toolResultMap = buildToolResultMap(messages)
  const finishTaskIds = new Set()

  messages.forEach((message) => {
    if (!hasToolCalls(message)) return
    message.tool_calls.forEach((toolCall) => {
      if (toolCall?.function?.name === 'sys_finish_task' && toolCall.id) {
        finishTaskIds.add(toolCall.id)
      }
    })
  })

  const normalized = []

  messages.forEach((message) => {
    if (isToolResultMessage(message) && finishTaskIds.has(message.tool_call_id)) {
      return
    }

    if (!hasToolCalls(message)) {
      normalized.push(message)
      return
    }

    const finishCalls = []
    const otherCalls = []

    message.tool_calls.forEach((toolCall) => {
      if (toolCall?.function?.name === 'sys_finish_task') {
        finishCalls.push(toolCall)
      } else {
        otherCalls.push(toolCall)
      }
    })

    if (otherCalls.length > 0) {
      normalized.push({
        ...message,
        tool_calls: otherCalls
      })
    }

    finishCalls.forEach((toolCall) => {
      const syntheticMessage = createFinishTaskMessage(message, toolCall, toolResultMap.get(toolCall.id))
      if (syntheticMessage) {
        normalized.push(syntheticMessage)
        return
      }
      normalized.push(createPendingFinishTaskMessage(message, toolCall))
    })
  })

  return normalized
}

const createMessageItem = (message, messageIndex, renderMessages) => ({
  id: `message:${message.message_id || messageIndex}`,
  type: 'message',
  message,
  messageIndex,
  renderMessages
})

const splitTurns = (messages) => {
  const turns = []
  let currentTurn = null

  messages.forEach((message, index) => {
    if (message?.role === 'user') {
      if (currentTurn?.messages.length) {
        turns.push(currentTurn)
      }
      currentTurn = {
        id: `turn:${message.message_id || index}`,
        messages: [message],
        indices: [index]
      }
      return
    }

    if (!currentTurn) {
      currentTurn = {
        id: `turn:prelude:${index}`,
        messages: [],
        indices: []
      }
    }

    currentTurn.messages.push(message)
    currentTurn.indices.push(index)
  })

  if (currentTurn?.messages.length) {
    turns.push(currentTurn)
  }

  return turns
}

const isRetainedAssistantMessage = (message) => (
  message?.role === 'assistant' &&
  !hasToolCalls(message) &&
  !isToolResultMessage(message) &&
  !RETAINED_ASSISTANT_EXCLUDED_TYPES.has(message?.message_type) &&
  !RETAINED_ASSISTANT_EXCLUDED_TYPES.has(message?.type) &&
  hasVisibleContent(message)
)

const getToolCallNames = (messages) => messages.flatMap(message => (
  Array.isArray(message?.tool_calls)
    ? message.tool_calls.map(toolCall => toolCall?.function?.name).filter(Boolean)
    : []
))

const getActionCodeForToolName = (toolName) => {
  if (!toolName) return TOOL_ACTION_CODES.use_tools
  if (
    toolName.includes('search') ||
    toolName.includes('view') ||
    toolName.includes('fetch') ||
    toolName.includes('read') ||
    toolName.includes('recall')
  ) {
    return TOOL_ACTION_CODES.inspect_info
  }
  if (
    toolName.includes('write') ||
    toolName.includes('update') ||
    toolName.includes('rename') ||
    toolName.includes('delete') ||
    toolName.includes('file')
  ) {
    return TOOL_ACTION_CODES.edit_files
  }
  if (
    toolName.includes('command') ||
    toolName.includes('execute') ||
    toolName.includes('shell') ||
    toolName.includes('python') ||
    toolName.includes('javascript')
  ) {
    return TOOL_ACTION_CODES.run_commands
  }
  if (toolName === 'sys_delegate_task') return TOOL_ACTION_CODES.delegate_tasks
  if (toolName === 'sys_spawn_agent') return TOOL_ACTION_CODES.create_agents
  if (toolName.includes('task') || toolName.includes('todo')) return TOOL_ACTION_CODES.manage_tasks
  if (toolName.includes('questionnaire') || toolName.includes('followup')) return TOOL_ACTION_CODES.collect_input
  if (toolName.includes('image') || toolName.includes('ppt') || toolName.includes('slide')) return TOOL_ACTION_CODES.generate_assets
  return TOOL_ACTION_CODES.use_tools
}

const summarizeActionCode = (messages) => {
  const counts = new Map()
  getToolCallNames(messages).forEach((toolName) => {
    const code = getActionCodeForToolName(toolName)
    counts.set(code, (counts.get(code) || 0) + 1)
  })

  if (counts.size === 0) return TOOL_ACTION_CODES.process_updates

  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])[0][0]
}

const getExecutionGroupDurationMs = (messages, previousMessage) => {
  if (!messages.length) return null
  const endTimestamp = toTimestampMs(messages[messages.length - 1]?.timestamp)
  const startTimestamp = toTimestampMs(previousMessage?.timestamp)
  if (startTimestamp !== null && endTimestamp !== null) {
    return Math.max(0, endTimestamp - startTimestamp)
  }

  const fallbackStartTimestamp = toTimestampMs(messages[0]?.timestamp)
  if (fallbackStartTimestamp === null || endTimestamp === null) return null
  return Math.max(0, endTimestamp - fallbackStartTimestamp)
}

const getGroupDurationMs = (messages) => {
  if (!messages.length) return null
  const startTimestamp = toTimestampMs(messages[0]?.timestamp)
  const endTimestamp = toTimestampMs(messages[messages.length - 1]?.timestamp)
  if (startTimestamp === null || endTimestamp === null) return null
  return Math.max(0, endTimestamp - startTimestamp)
}

const buildToolGroupItem = (turnId, messages, indices, options = {}) => {
  const previousMessage = options.previousMessage || null
  const startTimestampMs =
    toTimestampMs(previousMessage?.timestamp) ??
    toTimestampMs(messages[0]?.timestamp)
  return {
    id: `tool-group:${turnId}:${indices[0] ?? 0}`,
    type: 'tool_group',
    messages,
    messageIndices: indices,
    actionCode: summarizeActionCode(messages),
    durationMs: getExecutionGroupDurationMs(messages, previousMessage),
    startTimestampMs,
  }
}

const buildTurnSummaryItem = (turnId, messages, indices) => ({
  id: `turn-summary:${turnId}`,
  type: 'turn_summary',
  messages,
  messageIndices: indices,
  actionCode: summarizeActionCode(messages),
  durationMs: getGroupDurationMs(messages)
})

export const buildExecutionDisplayItems = (messages = []) => ({
  items: messages.map((message, index) => createMessageItem(message, index, messages))
})

export const buildDeliveryDisplayItems = (messages = [], { isLoading = false } = {}) => {
  const turns = splitTurns(messages)
  const items = []

  turns.forEach((turn, turnIndex) => {
    const isLatestTurn = turnIndex === turns.length - 1
    const isExecutingTurn = isLatestTurn && isLoading
    const tailTokenMessages = []
    const visibleMessages = [...turn.messages]
    const visibleIndices = [...turn.indices]

    while (visibleMessages.length > 0 && isTokenUsageMessage(visibleMessages[visibleMessages.length - 1])) {
      tailTokenMessages.unshift(visibleMessages.pop())
      visibleIndices.pop()
    }

    if (!visibleMessages.length) {
      tailTokenMessages.forEach((message, index) => {
        items.push(createMessageItem(message, turn.indices[turn.indices.length - tailTokenMessages.length + index], messages))
      })
      return
    }

    if (isExecutingTurn) {
      let cursor = 0
      while (cursor < visibleMessages.length) {
        if (isToolRelatedMessage(visibleMessages[cursor])) {
          const groupStartIndex = cursor
          const groupedMessages = []
          const groupedIndices = []
          while (cursor < visibleMessages.length && isToolRelatedMessage(visibleMessages[cursor])) {
            groupedMessages.push(visibleMessages[cursor])
            groupedIndices.push(visibleIndices[cursor])
            cursor += 1
          }
          const previousMessage = groupStartIndex > 0
            ? visibleMessages[groupStartIndex - 1]
            : null
          items.push(buildToolGroupItem(turn.id, groupedMessages, groupedIndices, { previousMessage }))
          continue
        }

        items.push(createMessageItem(visibleMessages[cursor], visibleIndices[cursor], messages))
        cursor += 1
      }
      tailTokenMessages.forEach((message, index) => {
        const messageIndex = turn.indices[turn.indices.length - tailTokenMessages.length + index]
        items.push(createMessageItem(message, messageIndex, messages))
      })
      return
    }

    let retainedIndex = -1
    for (let i = visibleMessages.length - 1; i >= 0; i -= 1) {
      if (isRetainedAssistantMessage(visibleMessages[i])) {
        retainedIndex = i
        break
      }
    }

    if (retainedIndex === -1) {
      if (visibleMessages[0]?.role === 'user') {
        items.push(createMessageItem(visibleMessages[0], visibleIndices[0], messages))
        const summaryMessages = visibleMessages.slice(1)
        const summaryIndices = visibleIndices.slice(1)
        if (summaryMessages.length > 0) {
          items.push(buildTurnSummaryItem(turn.id, summaryMessages, summaryIndices))
        }
      } else {
        visibleMessages.forEach((message, index) => {
          items.push(createMessageItem(message, visibleIndices[index], messages))
        })
      }
      tailTokenMessages.forEach((message, index) => {
        const messageIndex = turn.indices[turn.indices.length - tailTokenMessages.length + index]
        items.push(createMessageItem(message, messageIndex, messages))
      })
      return
    }

    if (visibleMessages[0]?.role === 'user') {
      items.push(createMessageItem(visibleMessages[0], visibleIndices[0], messages))
    }

    const summaryMessages = []
    const summaryIndices = []

    visibleMessages.forEach((message, index) => {
      if (index === retainedIndex) return
      if (message?.role === 'user') return
      summaryMessages.push(message)
      summaryIndices.push(visibleIndices[index])
    })

    if (summaryMessages.length > 0) {
      items.push(buildTurnSummaryItem(turn.id, summaryMessages, summaryIndices))
    }

    items.push(createMessageItem(visibleMessages[retainedIndex], visibleIndices[retainedIndex], messages))
    tailTokenMessages.forEach((message, index) => {
      const messageIndex = turn.indices[turn.indices.length - tailTokenMessages.length + index]
      items.push(createMessageItem(message, messageIndex, messages))
    })
  })

  return { items }
}
