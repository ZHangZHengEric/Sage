import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

import { normalizeFilePath } from '@/utils/fileIcons.js'

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
    const validItems = items.value.filter(item => item && item.type)
    if (!currentSessionId.value) {
        console.log('[Workbench] filteredItems: no session id, returning all', validItems.length)
        return validItems
    }
    const filtered = validItems.filter(item => item.sessionId === currentSessionId.value)
    console.log('[Workbench] filteredItems:', {
        currentSessionId: currentSessionId.value,
        total: validItems.length,
        filtered: filtered.length,
        firstItemSessionId: validItems[0]?.sessionId
    })
    return filtered
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
    if (item.type === 'file' && (item.data?.filePath || item.data?.path)) {
      const normalizedPath = normalizeFilePath(item.data.filePath || item.data.path)
      if (item.data.filePath) item.data.filePath = normalizedPath
      if (item.data.path) item.data.path = normalizedPath
    }

    // 检查是否已存在相同的项（根据 type 和唯一标识）
    const existingItem = items.value.find(i => {
      if (i.type !== item.type) return false
      // 文件类型：同一路径的不同版本也要保留，因此不在这里去重
      if (item.type === 'file') {
        return false
      }
      // 代码块类型：根据 code 内容去重
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
      if (item.type === 'file') {
        existingItem.timestamp = Date.now()
        existingItem.refreshVersion = (existingItem.refreshVersion || 0) + 1
      }

      // 如果存在但没有 agentId，更新它
      if (!existingItem.agentId && item.agentId) {
        console.log('[Workbench] Updating missing agentId for existing item:', item.agentId)
        existingItem.agentId = item.agentId
      }
      
      // 如果处于实时模式且是当前会话的项，尝试跳转到该项（针对流式输出时已存在但需要聚焦的情况）
      if (isRealtime.value && existingItem.sessionId === currentSessionId.value) {
         // 找到该项在 filteredItems 中的索引
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
  const extractFromMessage = (message, agentId = null) => {
    if (!message) return

    // 只处理 AI 和 Tool 的消息，跳过用户消息
    if (message.role !== 'assistant' && message.role !== 'tool') {
      return
    }

    const timestamp = message.timestamp || Date.now()
    const role = message.role
    const sessionId = message.session_id || currentSessionId.value
    const messageId = message.message_id || message.id
    // 优先使用传入的 agentId，其次是 message 中的 agent_id
    const finalAgentId = agentId || message.agent_id

    console.log('[Workbench] extractFromMessage:', {
      messageId,
      role,
      sessionId,
      agentId: finalAgentId,
      currentSessionId: currentSessionId.value,
      hasToolCalls: !!(message.tool_calls && message.tool_calls.length > 0),
      toolCallsCount: message.tool_calls?.length || 0
    })

    // 处理工具调用
    if (message.tool_calls && message.tool_calls.length > 0) {
      message.tool_calls.forEach((toolCall, idx) => {
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
          agentId: finalAgentId, // 关联AgentID
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
      console.log('[Workbench] Adding file:', idx, file.fileName, file.filePath)
      addItem({
        type: 'file',
        role: role,
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId, // 关联消息ID
        agentId: finalAgentId, // 关联AgentID
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
        agentId: finalAgentId, // 关联AgentID
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

// 提取 markdown 中的文件引用
export function extractFileReferences(content) {
  if (!content) return []

  if (typeof content !== 'string') {
    if (Array.isArray(content)) {
      content = content
        .map(item => {
          if (typeof item === 'string') return item
          if (item?.text) return item.text
          if (item?.content) return item.content
          return ''
        })
        .filter(Boolean)
        .join('\n')
    } else if (typeof content === 'object') {
      content = content.text || content.content || content.message || ''
    } else {
      content = String(content)
    }
  }

  const files = []

  // 匹配 [text](path)
  const markdownRegex = /\[([^\]]*?)\]\s*\(([^)]+?)\)/g
  let match

  while ((match = markdownRegex.exec(content)) !== null) {

    let fileName = match[1] || ''
    let path = match[2] || ''

    path = normalizeFilePath(path)

    if (!path || path.endsWith('/')) continue

    // 清理 fileName
    fileName = fileName.trim().replace(/^`|`$/g, '')

    // fallback 文件名
    if (!fileName) {
      fileName = path.split('/').pop()
    }

    files.push({
      filePath: path,
      fileName
    })
  }

  return files
}

function extractCodeBlocks(content) {
  if (!content) return []
  if (typeof content !== 'string') return []
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
