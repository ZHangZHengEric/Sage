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
  let itemIdCounter = 0 // 用于生成唯一 item id 的计数器

  // Getters
  // 按当前会话过滤的 items
  const filteredItems = computed(() => {
    // 过滤掉 null/undefined 项，并按当前会话过滤
    const validItems = items.value.filter(item => item && item.type)
    if (!currentSessionId.value) return validItems
    return validItems.filter(item => item.sessionId === currentSessionId.value)
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
    // 预处理文件路径
    if (item.type === 'file' && (item.data?.filePath || item.data?.path)) {
      let path = item.data.filePath || item.data.path
      
      // 1. 解码
      try {
        path = decodeURIComponent(path).trim()
      } catch (e) {
        console.warn('[Workbench] Failed to decode path:', path)
      }

      // 2. 去除反引号
      if (path.startsWith('`') && path.endsWith('`')) {
        path = path.slice(1, -1)
      }

      // 3. 处理 /sage-workspace/ 前缀
      if (path.startsWith('/sage-workspace/')) {
        path = path.replace('/sage-workspace/', '/')
      }

      // 4. 处理 file://
      if (path.startsWith('file://')) {
        path = path.replace(/^file:\/\/\/?/i, '/')
      }

      // 更新 item 数据
      if (item.data.filePath) item.data.filePath = path
      if (item.data.path) item.data.path = path
    }

    // 检查是否已存在相同的项（根据 type 和唯一标识）
    const existingItem = items.value.find(i => {
      if (i.type !== item.type) return false
      // 文件类型：根据 messageId + filePath 去重
      // 同一消息中的同一文件不重复，但不同消息可以重复（文件可能已修改）
      if (item.type === 'file') {
        const itemPath = item.data?.filePath || item.data?.path || ''
        const existingPath = i.data?.filePath || i.data?.path || ''
        const samePath = itemPath && existingPath && itemPath === existingPath
        const sameMessage = item.messageId && i.messageId && item.messageId === i.messageId
        // 只有路径相同且来自同一消息才认为是重复
        return samePath && sameMessage
      }
      // 代码块类型：根据 messageId + code 内容去重
      if (item.type === 'code' && item.data?.code) {
        const sameCode = i.data?.code === item.data.code
        const sameMessage = item.messageId && i.messageId && item.messageId === i.messageId
        return sameCode && sameMessage
      }
      // 工具调用类型：根据 toolCall id 去重
      if (item.type === 'tool_call' && item.data?.id) {
        return i.data?.id === item.data.id
      }
      return false
    })

    if (existingItem) {
      // 如果处于实时模式且是当前会话的项，尝试跳转到该项（针对流式输出时已存在但需要聚焦的情况）
      if (isRealtime.value && existingItem.sessionId === currentSessionId.value) {
        const index = filteredItems.value.indexOf(existingItem)
        if (index !== -1 && index !== currentIndex.value) {
          currentIndex.value = index
          console.log('[Workbench] Auto-jump to existing item index:', index)
        }
      }

      console.log('[Workbench] Item already exists, skipping:', {
        type: item.type,
        filePath: item.data?.filePath,
        toolCallId: item.data?.id
      })
      return existingItem
    }

    // 生成唯一 id：使用时间戳 + 计数器 + 随机数
    itemIdCounter++
    const newItem = {
      id: `item-${Date.now()}-${itemIdCounter}-${Math.random().toString(36).substr(2, 5)}`,
      timestamp: Date.now(),
      sessionId: currentSessionId.value, // 关联当前会话
      ...item
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

  // 重置所有状态（用于切换会话或退出页面）
  const resetState = () => {
    console.log('[Workbench] resetState - clearing all state')
    items.value = []
    currentIndex.value = 0
    isRealtime.value = true // 默认实时模式
    isListView.value = false
    currentSessionId.value = null
    pendingToolResults.value.clear()
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
        // 跳过无效的 toolCall
        if (!toolCall || !toolCall.function) {
          console.warn('[Workbench] Skipping invalid toolCall:', idx, toolCall)
          return
        }
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

  // 更新工具结果 - 简化逻辑，直接更新，不依赖 pendingToolResults
  const updateToolResult = (toolCallId, result) => {
    console.log('[Workbench] updateToolResult called with:', toolCallId, result)
    const item = items.value.find(i =>
      i.type === 'tool_call' && i.data.id === toolCallId
    )
    if (item) {
      item.toolResult = result
      console.log('[Workbench] Tool result updated for:', toolCallId)
      return true
    } else {
      console.log('[Workbench] Tool call item not found for:', toolCallId)
      return false
    }
  }

  return {
    // State
    items,
    currentIndex,
    isRealtime,
    isListView,
    currentSessionId,
    pendingToolResults,
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
    resetState,
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

    // 处理路径中的编码和空白字符
    try {
      path = decodeURIComponent(path).trim()
    } catch (e) {
      console.warn('[Workbench] Failed to decode path:', path)
    }

    if (path.startsWith('file://')) {
      path = path.replace(/^file:\/\/\/?/i, '/')
    }

    // 过滤掉文件夹路径（以 / 结尾的路径）
    if (path.startsWith('/') && !path.endsWith('/')) {
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
