import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useWorkbenchStore = defineStore('workbench', () => {
  // State
  const items = ref([])
  const currentIndex = ref(0)
  const isRealtime = ref(true)
  const isListView = ref(false)
  const currentSessionId = ref(null) // 当前会话ID
  const pendingToolResults = ref(new Map()) // 待处理的工具结果

  // Getters
  // 按当前会话过滤的 items
  const filteredItems = computed(() => {
    if (!currentSessionId.value) return items.value
    return items.value.filter(item => item.sessionId === currentSessionId.value)
  })

  const totalItems = computed(() => filteredItems.value.length)

  const currentItem = computed(() => {
    const items = filteredItems.value
    if (items.length === 0) return null
    // 确保索引在有效范围内
    const validIndex = Math.min(currentIndex.value, items.length - 1)
    return items[validIndex] || null
  })

  const maxIndex = computed(() => Math.max(0, filteredItems.value.length - 1))

  // 通过 messageId 和 itemIndex 查找 item 的索引
  const findItemIndexByMessageId = (messageId, itemIndex = 0) => {
    const filtered = filteredItems.value
    let matchCount = 0
    for (let i = 0; i < filtered.length; i++) {
      if (filtered[i].messageId === messageId) {
        if (matchCount === itemIndex) {
          return i
        }
        matchCount++
      }
    }
    return -1
  }

  // Actions
  const setSessionId = (sessionId) => {
    console.log('[Workbench] setSessionId:', sessionId)
    currentSessionId.value = sessionId
    // 切换会话后，自动跳转到该会话的最后一项
    setTimeout(() => {
      const filteredLength = filteredItems.value.length
      if (filteredLength > 0) {
        currentIndex.value = filteredLength - 1
        console.log('[Workbench] Auto-jump to last item:', currentIndex.value)
      } else {
        currentIndex.value = 0
      }
    }, 0)
  }

  const addItem = (item) => {
    // 检查是否有待处理的工具结果
    let toolResult = item.toolResult
    if (item.type === 'tool_call' && item.data?.id && pendingToolResults.value.has(item.data.id)) {
      toolResult = pendingToolResults.value.get(item.data.id)
      pendingToolResults.value.delete(item.data.id)
      console.log('[Workbench] Applied pending tool result for:', item.data.id)
    }

    const newItem = {
      id: `item-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now(),
      sessionId: currentSessionId.value, // 关联当前会话
      ...item,
      toolResult: toolResult
    }
    items.value.push(newItem)

    console.log('[Workbench] addItem:', {
      id: newItem.id,
      type: newItem.type,
      sessionId: newItem.sessionId,
      hasToolResult: !!newItem.toolResult,
      toolResultKeys: newItem.toolResult ? Object.keys(newItem.toolResult) : [],
      currentSessionId: currentSessionId.value,
      totalItems: items.value.length,
      filteredItemsCount: filteredItems.value.length
    })

    // 如果在实时模式，自动跳转到最新
    // 只有当新添加的 item 属于当前会话时才跳转
    if (isRealtime.value && newItem.sessionId === currentSessionId.value) {
      const filteredLength = filteredItems.value.length
      currentIndex.value = Math.max(0, filteredLength - 1)
      console.log('[Workbench] Auto-jump to index:', currentIndex.value)
    }

    return newItem
  }

  const clearItems = () => {
    console.log('[Workbench] clearItems')
    items.value = []
    currentIndex.value = 0
  }

  // 清除当前会话的 items
  const clearSessionItems = (sessionId) => {
    console.log('[Workbench] clearSessionItems:', sessionId)
    items.value = items.value.filter(item => item.sessionId !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentIndex.value = 0
    }
  }

  const setCurrentIndex = (index) => {
    const validIndex = Math.max(0, Math.min(maxIndex.value, index))
    console.log('[Workbench] setCurrentIndex:', index, '->', validIndex, 'maxIndex:', maxIndex.value)
    currentIndex.value = validIndex
  }

  // 通过 messageId 和 itemIndex 设置当前索引
  const setCurrentIndexByMessageId = (messageId, itemIndex = 0) => {
    const index = findItemIndexByMessageId(messageId, itemIndex)
    console.log('[Workbench] setCurrentIndexByMessageId:', messageId, itemIndex, '->', index)
    if (index !== -1) {
      setCurrentIndex(index)
      return true
    }
    return false
  }

  const toggleRealtime = () => {
    isRealtime.value = !isRealtime.value
    console.log('[Workbench] toggleRealtime:', isRealtime.value)
    if (isRealtime.value) {
      // 开启实时模式时，跳转到最新
      const filteredLength = filteredItems.value.length
      currentIndex.value = Math.max(0, filteredLength - 1)
    }
  }

  const setRealtime = (value) => {
    console.log('[Workbench] setRealtime:', value)
    isRealtime.value = value
    if (value) {
      const filteredLength = filteredItems.value.length
      currentIndex.value = Math.max(0, filteredLength - 1)
    }
  }

  const toggleListView = () => {
    isListView.value = !isListView.value
    console.log('[Workbench] toggleListView:', isListView.value)
  }

  const setListView = (value) => {
    console.log('[Workbench] setListView:', value)
    isListView.value = value
  }

  // 从消息中提取工作台项（用于历史消息加载）
  // 只处理 AI (assistant) 和 Tool 的消息，不处理用户消息
  const extractFromMessage = (message) => {
    if (!message) return

    // 只处理 AI 和 Tool 的消息，跳过用户消息
    if (message.role !== 'assistant' && message.role !== 'tool') {
      return
    }

    const timestamp = message.timestamp || Date.now()
    const role = message.role
    const sessionId = message.session_id || currentSessionId.value
    const messageId = message.message_id || message.id

    console.log('[Workbench] extractFromMessage:', {
      messageId,
      role,
      sessionId,
      currentSessionId: currentSessionId.value,
      hasToolCalls: !!(message.tool_calls && message.tool_calls.length > 0),
      toolCallsCount: message.tool_calls?.length || 0
    })

    // 处理工具调用
    if (message.tool_calls && message.tool_calls.length > 0) {
      message.tool_calls.forEach((toolCall, idx) => {
        console.log('[Workbench] Adding tool_call:', idx, toolCall.function?.name)
        addItem({
          type: 'tool_call',
          role: role,
          timestamp: timestamp,
          sessionId: sessionId,
          messageId: messageId, // 关联消息ID
          data: toolCall,
          toolResult: null // 工具结果会在后续更新
        })
      })
    }

    // 处理文件引用
    const fileMatches = extractFileReferences(message.content)
    if (fileMatches.length > 0) {
      console.log('[Workbench] Found files:', fileMatches.length)
    }
    fileMatches.forEach((file, idx) => {
      console.log('[Workbench] Adding file:', idx, file.fileName)
      addItem({
        type: 'file',
        role: role,
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId, // 关联消息ID
        data: file
      })
    })

    // 处理代码块
    const codeBlocks = extractCodeBlocks(message.content)
    if (codeBlocks.length > 0) {
      console.log('[Workbench] Found code blocks:', codeBlocks.length)
    }
    codeBlocks.forEach((code, idx) => {
      console.log('[Workbench] Adding code block:', idx, code.language)
      addItem({
        type: 'code',
        role: role,
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId, // 关联消息ID
        data: code
      })
    })
  }

  // 更新工具结果
  const updateToolResult = (toolCallId, result) => {
    console.log('[Workbench] updateToolResult called with:', toolCallId, result)
    const item = items.value.find(i =>
      i.type === 'tool_call' && i.data.id === toolCallId
    )
    if (item) {
      item.toolResult = result
      console.log('[Workbench] Tool result updated for:', toolCallId)
    } else {
      // 如果找不到 item，存入待处理队列
      pendingToolResults.value.set(toolCallId, result)
      console.log('[Workbench] Tool result stored in pending queue for:', toolCallId)
    }
  }

  return {
    // State
    items,
    currentIndex,
    isRealtime,
    isListView,
    currentSessionId,
    // Getters
    filteredItems,
    totalItems,
    currentItem,
    maxIndex,
    findItemIndexByMessageId,
    // Actions
    setSessionId,
    addItem,
    clearItems,
    clearSessionItems,
    setCurrentIndex,
    setCurrentIndexByMessageId,
    toggleRealtime,
    setRealtime,
    toggleListView,
    setListView,
    extractFromMessage,
    updateToolResult
  }
})

// 辅助函数
function extractFileReferences(content) {
  if (!content) return []
  const files = []
  const markdownRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match

  while ((match = markdownRegex.exec(content)) !== null) {
    let path = match[2]
    const fileName = match[1]

    if (path.startsWith('file://')) {
      path = path.replace(/^file:\/\/\/?/i, '/')
    }

    if (path.startsWith('/')) {
      files.push({
        filePath: path,
        fileName: fileName || path.split('/').pop()
      })
    }
  }

  return files
}

function extractCodeBlocks(content) {
  if (!content) return []
  const codeBlocks = []
  const codeRegex = /```(\w+)?\n([\s\S]*?)```/g
  let match

  while ((match = codeRegex.exec(content)) !== null) {
    codeBlocks.push({
      language: match[1] || 'text',
      code: match[2].trim()
    })
  }

  return codeBlocks
}
