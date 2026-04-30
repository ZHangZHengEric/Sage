import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

import { normalizeFilePath } from '@/utils/fileIcons.js'
import { mergeToolFunctionArguments } from '@/utils/mergeToolFunctionArguments.js'

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

  const findItemIndexByStableKey = (stableKey) => {
    if (!stableKey) return -1
    return filteredItems.value.findIndex(item => item?.stableKey === stableKey)
  }

  // Actions
  const compactSessionItems = (sessionId) => {
    if (!sessionId) return
    const seen = new Set()
    const nextItems = []

    for (const item of items.value) {
      if (!item || item.sessionId !== sessionId) {
        nextItems.push(item)
        continue
      }

      let dedupKey = null
      if (item.stableKey) {
        dedupKey = `stable:${item.stableKey}`
      } else if (item.type === 'file') {
        const path = item.data?.filePath || item.data?.path || item.data?.src || ''
        dedupKey = `file:${item.messageId || ''}:${path}`
      } else if (item.type === 'tool_call' && item.data?.id) {
        dedupKey = `tool:${item.data.id}`
      } else if (item.type === 'code' && item.data?.code) {
        dedupKey = `code:${item.messageId || ''}:${item.data.code}`
      }

      if (dedupKey && seen.has(dedupKey)) {
        continue
      }
      if (dedupKey) {
        seen.add(dedupKey)
      }
      nextItems.push(item)
    }

    items.value = nextItems
  }

  const setSessionId = (sessionId, options = {}) => {
    const { autoJumpToLast = true } = options
    if (currentSessionId.value === sessionId) {
      console.log('[Workbench] setSessionId skipped (unchanged):', sessionId)
      return
    }
    console.log('[Workbench] setSessionId:', sessionId)
    currentSessionId.value = sessionId
    compactSessionItems(sessionId)
    if (!autoJumpToLast) {
      return
    }
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

    const stableKey = item.stableKey || buildStableKey(item)
    if (stableKey) {
      item.stableKey = stableKey
    }

    // 检查是否已存在相同的项（根据稳定键或 type+唯一标识）
    const existingItem = items.value.find(i => {
      if (stableKey && i?.stableKey === stableKey) return true
      if (i.type !== item.type) return false
      // 文件类型：同一消息内同一路径去重，避免流式更新导致重复堆积
      if (item.type === 'file') {
        const newPath = item.data?.filePath || item.data?.path || item.data?.src || ''
        const oldPath = i.data?.filePath || i.data?.path || i.data?.src || ''
        const sameMessage = item.messageId && i.messageId && item.messageId === i.messageId
        return sameMessage && newPath === oldPath
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

      if (item.type === 'tool_call') {
        existingItem.data = mergeToolCallData(existingItem.data, item.data)
        if (item.toolResult) {
          existingItem.toolResult = item.toolResult
        }
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
      stableKey: stableKey || item.stableKey || null,
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

    // tool_call item 落地后，把可能先到的 progress 缓存灌进去
    if (newItem.type === 'tool_call') {
      const tcId = newItem.data?.id || newItem.data?.tool_call_id
      if (tcId && pendingToolProgress.value.has(tcId)) {
        const buf = pendingToolProgress.value.get(tcId)
        pendingToolProgress.value.delete(tcId)
        if (buf.liveOutput) {
          newItem.liveOutput = buf.liveOutput
          newItem.liveSegments = buf.liveSegments
        }
        newItem.live = buf.live
      }
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

  const setCurrentIndexByStableKey = (stableKey) => {
    const index = findItemIndexByStableKey(stableKey)
    console.log('[Workbench] setCurrentIndexByStableKey:', stableKey, '->', index)
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

  const mergeToolCallData = (existingData = {}, incomingData = {}) => {
    if (!incomingData || typeof incomingData !== 'object') return existingData
    if (!existingData || typeof existingData !== 'object') return { ...incomingData }

    const existingFn = existingData.function && typeof existingData.function === 'object'
      ? existingData.function
      : {}
    const incomingFn = incomingData.function && typeof incomingData.function === 'object'
      ? incomingData.function
      : {}

    const mergedFn = { ...existingFn, ...incomingFn }
    if (existingFn.name && !incomingFn.name) mergedFn.name = existingFn.name
    if (incomingFn.name) mergedFn.name = incomingFn.name

    mergedFn.arguments = mergeToolFunctionArguments(existingFn.arguments, incomingFn.arguments)

    const mergedData = {
      ...existingData,
      ...incomingData,
      function: mergedFn
    }

    if (existingData.id && !incomingData.id) {
      mergedData.id = existingData.id
    }
    if (existingData.tool_call_id && !incomingData.tool_call_id) {
      mergedData.tool_call_id = existingData.tool_call_id
    }
    if (existingData.index !== undefined && incomingData.index === undefined) {
      mergedData.index = existingData.index
    }

    return mergedData
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
    // 协议性内置工具（如 turn_status）只是 agent 控制信号，不进入工作台 timeline。
    const HIDDEN_WORKBENCH_TOOL_NAMES = new Set(['turn_status'])
    if (message.tool_calls && message.tool_calls.length > 0) {
      message.tool_calls.forEach((toolCall, idx) => {
        if (!toolCall || !toolCall.function) {
          console.warn('[Workbench] Skipping invalid toolCall:', idx, toolCall)
          return
        }
        if (HIDDEN_WORKBENCH_TOOL_NAMES.has(toolCall.function?.name)) {
          return
        }
        console.log('[Workbench] Adding tool_call:', idx, toolCall.function?.name)
        const toolStableKey = messageId ? `tool:${messageId}:${idx}` : (toolCall.id ? `tool:${toolCall.id}` : null)
        addItem({
          type: 'tool_call',
          role: role,
          timestamp: timestamp,
          sessionId: sessionId,
          messageId: messageId, // 关联消息ID
          agentId: finalAgentId, // 关联AgentID
          stableKey: toolStableKey,
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
      i.type === 'tool_call' && (i.data.id === toolCallId || i.data.tool_call_id === toolCallId)
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

  // tool_call_id 还没匹配到 workbench item 时缓存的 progress 文本
  // 一旦对应的 tool_call item 被 addItem 创建，flushPendingToolProgress 会把缓存灌进去
  const pendingToolProgress = ref(new Map())

  // 从工具实时执行通道追加增量文本（stdout/stderr）。
  // - 同一 tool_call_id 的所有 progress 累加到 item.liveOutput；
  // - 按 stream 字段保留分段信息以便前端按通道渲染（item.liveSegments）；
  // - closed=true 表示该 tool 的 progress 流结束，前端可收起 spinner。
  // 不影响 item.toolResult（最终工具结果由现有 updateToolResult 写入）。
  const appendToolProgress = ({ toolCallId, text = '', stream = 'stdout', closed = false, ts = null }) => {
    if (!toolCallId) return false
    const item = items.value.find(i =>
      i.type === 'tool_call' && (i.data.id === toolCallId || i.data.tool_call_id === toolCallId)
    )
    if (!item) {
      // 工具卡片还没创建（极少数情况：progress 事件先于 tool_call 消息到达）
      const buf = pendingToolProgress.value.get(toolCallId) || { liveOutput: '', liveSegments: [], live: true }
      if (text) {
        buf.liveOutput += text
        buf.liveSegments.push({ stream, text, ts })
      }
      if (closed) buf.live = false
      pendingToolProgress.value.set(toolCallId, buf)
      return false
    }
    if (text) {
      item.liveOutput = (item.liveOutput || '') + text
      if (!Array.isArray(item.liveSegments)) item.liveSegments = []
      item.liveSegments.push({ stream, text, ts })
    }
    if (closed) {
      item.live = false
    } else {
      item.live = true
    }
    return true
  }

  const flushPendingToolProgress = (toolCallId) => {
    const buf = pendingToolProgress.value.get(toolCallId)
    if (!buf) return
    pendingToolProgress.value.delete(toolCallId)
    const item = items.value.find(i =>
      i.type === 'tool_call' && (i.data.id === toolCallId || i.data.tool_call_id === toolCallId)
    )
    if (!item) return
    if (buf.liveOutput) {
      item.liveOutput = (item.liveOutput || '') + buf.liveOutput
      if (!Array.isArray(item.liveSegments)) item.liveSegments = []
      item.liveSegments.push(...buf.liveSegments)
    }
    item.live = buf.live
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
    findItemIndexByStableKey,
    // Actions
    compactSessionItems,
    setSessionId,
    addItem,
    clearItems,
    resetState,
    clearSessionItems,
    setCurrentIndex,
    setCurrentIndexByMessageId,
    setCurrentIndexByStableKey,
    toggleRealtime,
    setRealtime,
    toggleListView,
    setListView,
    extractFromMessage,
    updateToolResult,
    appendToolProgress,
    flushPendingToolProgress,
    pendingToolProgress
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

function normalizeFilePathForStableKey(path) {
  if (!path) return ''
  return normalizeFilePath(path)
}

function buildStableKey(item) {
  if (!item || !item.type) return null
  const messageId = item.messageId || item.data?.message_id || item.data?.messageId || ''

  if (item.type === 'tool_call') {
    const toolCallId = item.data?.id || item.data?.tool_call_id || ''
    if (messageId && toolCallId) return `tool:${messageId}:${toolCallId}`
    if (toolCallId) return `tool:${toolCallId}`
    return null
  }

  if (item.type === 'file') {
    const path = normalizeFilePathForStableKey(item.data?.filePath || item.data?.path || item.data?.src || '')
    if (!path) return null
    if (messageId) return `file:${messageId}:${path}`
    return `file:${path}`
  }

  if (item.type === 'code' && messageId && item.data?.code) {
    return `code:${messageId}:${item.data.code}`
  }

  if (messageId) return `${item.type}:${messageId}`
  return null
}
