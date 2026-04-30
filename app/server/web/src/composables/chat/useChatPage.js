import { ref, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import SparkMD5 from 'spark-md5'
import { useLanguage } from '@/utils/i18n.js'
import { useLanguageStore } from '@/utils/i18n.js'
import { chatAPI } from '@/api/chat.js'
import { agentAPI } from '@/api/agent.js'
import { useChatActiveSessionCache } from '@/composables/chat/useChatActiveSessionCache.js'
import { useChatScroll } from '@/composables/chat/useChatScroll.js'
import { useChatStream } from '@/composables/chat/useChatStream.js'
import { useChatLifecycle } from '@/composables/chat/useChatLifecycle.js'
import { useChatAgentConfig } from '@/composables/chat/useChatAgentConfig.js'
import { useChatWorkspace } from '@/composables/chat/useChatWorkspace.js'
import { usePanelStore } from '@/stores/panel.js'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { isToolResultMessage } from '@/utils/messageLabels.js'
import { mergeToolFunctionArguments } from '@/utils/mergeToolFunctionArguments.js'
import { storeToRefs } from 'pinia'

const abilityCacheByAgentGlobal = ref({})

export const useChatPage = (props) => {
  const { t } = useLanguage()
  const languageStore = useLanguageStore()
  const { language } = storeToRefs(languageStore)
  const panelStore = usePanelStore()
  const workbenchStore = useWorkbenchStore()
  const route = useRoute()
  const router = useRouter()

  const {
    activeSessions,
    handleActiveSessionsUpdated,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    markSessionInterrupted,
    removeSessionFromCache,
    deriveSessionTitle,
    startSSESync,
    stopSSESync
  } = useChatActiveSessionCache()

  const {
    messagesListRef,
    messagesEndRef,
    shouldAutoScroll,
    scrollToBottom,
    handleScroll,
    clearScrollTimer
  } = useChatScroll()
  // const showSettings = ref(false) // Use panelStore instead
  const currentTraceId = ref(null)
  const abilityItems = ref([])
  const abilityLoading = ref(false)
  const abilityError = ref(null)
  const showAbilityPanel = ref(false)
  const abilityPresetInput = ref('')
  const showAbilityButton = ref(true)
  const hasUsedAbilityEntryInSession = ref(false)


  // 打开工作台（统一方法）
  const openWorkbench = (options = {}) => {
    const { toolCallId = null, messageId = null, realtime = true } = options
    const toolStableKey = toolCallId
      ? (messageId ? `tool:${messageId}:${toolCallId}` : `tool:${toolCallId}`)
      : null

    // 打开工作台
    panelStore.openWorkbench()

    // 对齐当前会话，避免 filteredItems 过滤到错误会话导致定位失败
    const isLocateTarget = !!toolCallId || !!messageId
    const targetGlobalItem = toolStableKey
      ? (workbenchStore.items || []).find(item => item?.stableKey === toolStableKey)
      : (toolCallId
      ? (workbenchStore.items || []).find(item =>
          item?.type === 'tool_call' && item?.data?.id === toolCallId
        )
      : (messageId
          ? (workbenchStore.items || []).find(item => item?.messageId === messageId)
          : null))
    const targetSessionId = targetGlobalItem?.sessionId || currentSessionId.value
    if (currentSessionId.value) {
      workbenchStore.setSessionId(targetSessionId, {
        autoJumpToLast: !isLocateTarget
      })
    }

    // 设置实时模式
    if (realtime) {
      workbenchStore.setRealtime(true)
    }
    if (isLocateTarget) {
      workbenchStore.setRealtime(false)
    }

    // 如果指定了 toolCallId，跳转到对应项
    if (toolCallId || messageId) {
      const ensureToolCallItemExists = () => {
        if (!toolCallId) return
        const exists = (workbenchStore.items || []).some(item =>
          item?.type === 'tool_call' && item?.data?.id === toolCallId
        )
        if (exists) return

        const sourceMessage = (messages.value || []).find(message =>
          message?.session_id === targetSessionId &&
          Array.isArray(message?.tool_calls) &&
          message.tool_calls.some(call => (call?.id || call?.tool_call_id) === toolCallId)
        )
        if (sourceMessage) {
          const effectiveAgentId = sourceMessage.agent_id || selectedAgent.value?.id || selectedAgentId.value || null
          workbenchStore.extractFromMessage(sourceMessage, effectiveAgentId)
        }
      }

      const jumpToToolCall = () => {
        ensureToolCallItemExists()
        const filteredItems = workbenchStore.filteredItems || []
        let index = -1

        if (toolStableKey) {
          index = filteredItems.findIndex(item => item?.stableKey === toolStableKey)
        }

        if (index === -1 && toolCallId && targetGlobalItem?.id) {
          index = filteredItems.findIndex(item => item?.id === targetGlobalItem.id)
        }

        if (toolCallId && index === -1) {
          index = filteredItems.findIndex(item =>
            item?.type === 'tool_call' && item?.data?.id === toolCallId
          )
        }

        // 兜底：在全量 items 中找到后，映射回 filteredItems 索引
        if (toolCallId && index === -1) {
          const globalItem = (workbenchStore.items || []).find(item =>
            item?.type === 'tool_call' && item?.data?.id === toolCallId
          )
          if (globalItem) {
            index = filteredItems.findIndex(item => item?.id === globalItem.id)
          }
        }

        if (index === -1 && messageId) {
          index = filteredItems.findIndex(item => item?.messageId === messageId)
        }

        if (index !== -1) {
          workbenchStore.setCurrentIndex(index)
          workbenchStore.setRealtime(false)
          return true
        }
        return false
      }

      // 多次重试，覆盖面板挂载/会话切换/流式入库的异步时序
      const retryDelays = [0, 32, 120, 300]
      const initialMatched = jumpToToolCall()
      if (!initialMatched) {
        retryDelays.forEach((delay) => {
          setTimeout(() => {
            jumpToToolCall()
          }, delay)
        })
      } else {
        retryDelays.slice(1).forEach((delay) => {
          setTimeout(() => {
            jumpToToolCall()
          }, delay)
        })
      }
    }
  }

  // 切换面板（互斥）
  const togglePanel = (panel) => {
    if (panel === 'workbench') {
      // 使用统一方法打开工作台
      openWorkbench()
      showAbilityPanel.value = false
    } else if (panel === 'workspace') {
      if (panelStore.activePanel === 'workspace') {
        panelStore.closeAll()
      } else {
        panelStore.openWorkspace()
      }
      showAbilityPanel.value = false
    } else if (panel === 'settings') {
      if (panelStore.activePanel === 'settings') {
        panelStore.closeAll()
      } else {
        panelStore.openSettings()
      }
      showAbilityPanel.value = false
    }
  }

  const messages = ref([])
  const messageIdIndexMap = ref(new Map())
  const isLoading = ref(false)
  const loadingSessionId = ref(null)
  const abortControllerRef = ref(null)
  const currentSessionId = ref(null)
  const activeSubSessionId = ref(null)
  const isHistoryLoading = ref(false)

  const filteredMessages = computed(() => {
    if (!messages.value) return []
    if (!currentSessionId.value) return []
    return messages.value.filter(m => m.session_id === currentSessionId.value)
  })

  const isCurrentSessionLoading = computed(() =>
    !!isLoading.value &&
    !!currentSessionId.value &&
    loadingSessionId.value === currentSessionId.value
  )

  const subSessionMessages = computed(() => {
    if (!activeSubSessionId.value) return []
    return messages.value.filter(m => m.session_id === activeSubSessionId.value)
  })

  const handleOpenSubSession = (sessionId) => {
    activeSubSessionId.value = sessionId
  }

  const handleCloseSubSession = () => {
    activeSubSessionId.value = null
  }

  const rebuildMessageIdIndexMap = () => {
    const next = new Map()
    messages.value.forEach((item, index) => {
      if (item?.message_id) {
        next.set(item.message_id, index)
      }
    })
    messageIdIndexMap.value = next
  }

  const mergeToolCall = (existingToolCall = {}, incomingToolCall = {}) => {
    if (!incomingToolCall || typeof incomingToolCall !== 'object') return existingToolCall
    if (!existingToolCall || typeof existingToolCall !== 'object') return { ...incomingToolCall }

    const existingFn = existingToolCall.function && typeof existingToolCall.function === 'object'
      ? existingToolCall.function
      : {}
    const incomingFn = incomingToolCall.function && typeof incomingToolCall.function === 'object'
      ? incomingToolCall.function
      : {}

    const mergedFn = { ...existingFn, ...incomingFn }
    if (existingFn.name && !incomingFn.name) mergedFn.name = existingFn.name
    if (incomingFn.name) mergedFn.name = incomingFn.name

    // 与 sagents agent_base / stream_merger / fibre backend 一致：字符串增量拼接，禁止用 {} 覆盖已累计参数
    mergedFn.arguments = mergeToolFunctionArguments(existingFn.arguments, incomingFn.arguments)

    const mergedToolCall = {
      ...existingToolCall,
      ...incomingToolCall,
      function: mergedFn
    }

    if (existingToolCall.id && !incomingToolCall.id) {
      mergedToolCall.id = existingToolCall.id
    }
    if (existingToolCall.tool_call_id && !incomingToolCall.tool_call_id) {
      mergedToolCall.tool_call_id = existingToolCall.tool_call_id
    }
    if (existingToolCall.index !== undefined && incomingToolCall.index === undefined) {
      mergedToolCall.index = existingToolCall.index
    }

    return mergedToolCall
  }

  const mergeToolCalls = (existingToolCalls = [], incomingToolCalls = []) => {
    const existingList = Array.isArray(existingToolCalls) ? existingToolCalls : []
    const incomingList = Array.isArray(incomingToolCalls) ? incomingToolCalls : []

    if (incomingList.length === 0) {
      return existingList.filter(Boolean).map(tc => ({ ...tc }))
    }

    // 同一条 assistant 消息里多个工具调用是按 OpenAI delta 的 `index` 字段
    // 区分的，绝对不能用数组下标硬合并 —— 否则后到的 file_write 增量会被
    // 拼接到第一条 tool_call 上，造成"参数收集不到 / 工具从页面消失"。
    const result = existingList.filter(Boolean).map(tc => ({ ...tc }))

    const findTargetIdx = (incomingTC) => {
      if (!incomingTC) return -1
      const incomingId = incomingTC.id || incomingTC.tool_call_id
      if (incomingId) {
        const idx = result.findIndex(t => t && (t.id === incomingId || t.tool_call_id === incomingId))
        if (idx !== -1) return idx
      }
      if (incomingTC.index !== undefined && incomingTC.index !== null) {
        const idx = result.findIndex(t => t && t.index === incomingTC.index)
        if (idx !== -1) return idx
      }
      return -1
    }

    incomingList.forEach((incomingTC) => {
      if (!incomingTC) return
      const targetIdx = findTargetIdx(incomingTC)
      if (targetIdx !== -1) {
        result[targetIdx] = mergeToolCall(result[targetIdx], incomingTC)
      } else {
        result.push({ ...incomingTC })
      }
    })

    return result
  }

  const createSession = (_agentId = null) => {
    const sessionId = `session_${Date.now()}`
    currentSessionId.value = sessionId
    return sessionId
  }

  const syncSessionIdToRoute = async (sessionId) => {
    if (!sessionId) return
    if (route.query.session_id === sessionId) return
    await router.replace({
      query: {
        ...route.query,
        session_id: sessionId
      }
    })
  }

  const clearCurrentStreamViewState = () => {
    if (abortControllerRef.value) {
      abortControllerRef.value.abort()
      abortControllerRef.value = null
    }
    isLoading.value = false
    loadingSessionId.value = null
  }

  const loadConversationMessages = async (sessionId) => {
    // 进入会话时清空工作台
    workbenchStore.clearItems()
    workbenchStore.setSessionId(sessionId)
    console.log('[ChatPage] Cleared workbench for session:', sessionId)

    const res = await chatAPI.getConversationMessages(sessionId)
    if (!res) return null
    const conversationAgentId = res.conversation_info?.agent_id || null

    if (conversationAgentId) {
      const agent = agents.value.find(a => a.id === conversationAgentId)
      if (agent) {
        await selectAgent(agent)
      }
    }

    const normalizedMessages = (res.messages || []).map(msg => ({
      ...msg,
      session_id: msg.session_id || sessionId,
      agent_id: msg.agent_id || conversationAgentId
    }))
    messages.value = normalizedMessages
    rebuildMessageIdIndexMap()

    normalizedMessages.forEach((message) => {
      workbenchStore.extractFromMessage(message, message.agent_id || conversationAgentId)
      if (isToolResultMessage(message) && message.tool_call_id) {
        const plainToolResult = JSON.parse(JSON.stringify(message))
        workbenchStore.updateToolResult(message.tool_call_id, plainToolResult)
      }
    })

    const nextStreamIndex = Number(res.next_stream_index)
    if (Number.isFinite(nextStreamIndex) && nextStreamIndex >= 0) {
      updateActiveSessionLastIndex(sessionId, nextStreamIndex)
    }

    // 只有在有消息且有工作台 item 时，才自动打开工作台
    if (normalizedMessages.length > 0 && workbenchStore.filteredItems.length > 0) {
      openWorkbench({ realtime: true })
    }

    if (res.conversation_info && activeSessions.value[sessionId]?.status === 'running') {
      updateActiveSession(sessionId, true, res.conversation_info.title)
    }
    return res
  }

  const handleMessage = (messageData) => {
    if (messageData.type === 'stream_end') return
    if (messageData.type === 'tool_progress') {
      // 工具执行过程实时片段：不进 messages 列表、不进历史，仅追加到对应 tool 卡片的 live area
      try {
        workbenchStore.appendToolProgress({
          toolCallId: messageData.tool_call_id,
          text: messageData.text,
          stream: messageData.stream,
          closed: !!messageData.closed,
          ts: messageData.ts
        })
      } catch (e) {
        console.warn('[Chat] handle tool_progress failed:', e)
      }
      return
    }
    const messageId = messageData.message_id
    const extractWorkbenchFromMessage = (message) => {
      if (!message) return
      const effectiveAgentId = message.agent_id || selectedAgent.value?.id || selectedAgentId.value || null
      workbenchStore.extractFromMessage(message, effectiveAgentId)

      if (isToolResultMessage(message) && message.tool_call_id) {
        const plainToolResult = JSON.parse(JSON.stringify(message))
        workbenchStore.updateToolResult(message.tool_call_id, plainToolResult)
        return
      }

      if (message.tool_calls && message.tool_calls.length > 0) {
        message.tool_calls.forEach((toolCall) => {
          const toolResult = toolCall?.function?.result
          if (toolCall?.id && toolResult) {
            const plainToolResult = JSON.parse(JSON.stringify(toolResult))
            workbenchStore.updateToolResult(toolCall.id, plainToolResult)
          }
        })
      }
    }

    if (messageId && messageIdIndexMap.value.has(messageId)) {
      const targetIndex = messageIdIndexMap.value.get(messageId)
      const existing = messages.value[targetIndex]
      if (!existing) {
        rebuildMessageIdIndexMap()
        return
      }
      let nextMessage
      if (isToolResultMessage(messageData)) {
        nextMessage = {
          ...messageData,
          timestamp: messageData.timestamp || Date.now()
        }
      } else {
        nextMessage = {
          ...existing,
          ...messageData,
          content: (existing.content || '') + (messageData.content || ''),
          timestamp: messageData.timestamp || Date.now()
        }
        if (messageData.tool_calls || existing.tool_calls) {
          nextMessage.tool_calls = mergeToolCalls(existing.tool_calls || [], messageData.tool_calls || [])
        }
      }
      messages.value.splice(targetIndex, 1, nextMessage)
      extractWorkbenchFromMessage(nextMessage)
      return
    }
    const appended = {
      ...messageData,
      timestamp: messageData.timestamp || Date.now()
    }
    messages.value.push(appended)
    if (appended.message_id) {
      messageIdIndexMap.value.set(appended.message_id, messages.value.length - 1)
    }
    extractWorkbenchFromMessage(appended)
    shouldAutoScroll.value = true
    nextTick(() => scrollToBottom(true))
  }

  const addUserMessage = (content, sessionId, multimodalContent = null, enableMultimodal = false) => {
    // 根据 enableMultimodal 决定是否使用多模态格式
    // 只有当 enableMultimodal 为 true 且有多模态内容时，才使用数组格式
    console.log('enableMultimodal:', enableMultimodal)
    console.log('multimodalContent:', multimodalContent)
    const messageContent = (enableMultimodal && multimodalContent && multimodalContent.length > 0)
      ? multimodalContent
      : content.trim()

    const userMessage = {
      role: 'user',
      content: messageContent,
      message_id: Date.now().toString(),
      type: 'user_input',
      message_type: 'user_input',
      session_id: sessionId,
      timestamp: Date.now()
    }
    messages.value.push(userMessage)
    messageIdIndexMap.value.set(userMessage.message_id, messages.value.length - 1)
    return userMessage
  }

  const addErrorMessage = (error) => {
    const errorMessage = {
      role: 'assistant',
      content: `错误: ${error.message}`,
      message_id: Date.now().toString(),
      type: 'error',
      timestamp: Date.now()
    }
    messages.value.push(errorMessage)
    messageIdIndexMap.value.set(errorMessage.message_id, messages.value.length - 1)
  }

  const clearMessages = () => {
    messages.value = []
    messageIdIndexMap.value = new Map()
  }

  const {
    agents,
    selectedAgent,
    selectedAgentId,
    config,
    selectAgent,
    updateConfig,
    restoreSelectedAgent,
    loadAgents,
    handleAgentChange
  } = useChatAgentConfig({
    t,
    toast,
    clearMessages,
    createSession
  })

  const {
    showWorkspace,
    workspaceFiles,
    isWorkspaceLoading,
    downloadWorkspaceFile,
    downloadFile,
    deleteFile,
    refreshWorkspace,
    clearTaskAndWorkspace
  } = useChatWorkspace({
    t,
    toast,
    currentSessionId,
    selectedAgentId
  })

  const {
    handleSessionLoad,
    handleSendMessage,
    stopGeneration,
    rerunSession
  } = useChatStream({
    chatAPI,
    toast,
    t,
    activeSessions,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    markSessionInterrupted,
    deriveSessionTitle,
    shouldAutoScroll,
    scrollToBottom,
    isLoading,
    loadingSessionId,
    abortControllerRef,
    currentSessionId,
    selectedAgent,
    config,
    currentTraceId,
    syncSessionIdToRoute,
    addUserMessage,
    addErrorMessage,
    handleMessage,
    createSession,
    clearCurrentStreamViewState,
    loadConversationMessages,
    isHistoryLoading,
    removeSessionFromCache,
    language
  })

  const submitEditedLastUserMessage = async (content) => {
    const sessionId = currentSessionId.value
    if (!sessionId || !selectedAgent.value) return false

    const cleanedContent = String(content || '').trim()
    if (!cleanedContent) return false

    if (isLoading.value) {
      await stopGeneration()
      await new Promise(resolve => setTimeout(resolve, 300))
    }

    try {
      isLoading.value = true
      loadingSessionId.value = sessionId
      shouldAutoScroll.value = true

      await chatAPI.editLastUserMessage(sessionId, { content: cleanedContent })
      await loadConversationMessages(sessionId)

      updateActiveSession(
        sessionId,
        true,
        deriveSessionTitle(cleanedContent),
        cleanedContent,
        false
      )

      await rerunSession({
        sessionId,
        selectedAgent: selectedAgent.value,
        config: config.value,
        onMessage: (data) => {
          if (data.type === 'trace_info') {
            currentTraceId.value = data.trace_id
            return
          }
          handleMessage(data)
        },
        onComplete: () => {
          scrollToBottom()
          isLoading.value = false
          loadingSessionId.value = null
        },
        onError: (error) => {
          addErrorMessage(error)
          isLoading.value = false
          loadingSessionId.value = null
        }
      })
      return true
    } catch (error) {
      toast.error(t('chat.sendError'))
      isLoading.value = false
      loadingSessionId.value = null
      return false
    }
  }

  const showLoadingBubble = computed(() => !!isLoading.value)

  const resetChat = () => {
    persistRunningSessionOnLeaveChat()
    clearCurrentStreamViewState()
    clearMessages()
    clearTaskAndWorkspace()
    // 重置工作台所有状态
    workbenchStore.resetState()
    console.log('[ChatPage] Reset workbench state for new session')
    // 关闭工作台 panel
    panelStore.closeAll()
    console.log('[ChatPage] Closed panel for new session')
    showAbilityPanel.value = false
    abilityPresetInput.value = ''
    abilityError.value = null
    hasUsedAbilityEntryInSession.value = false
    showAbilityButton.value = true
    createSession()
  }

  const loadConversationData = async (conversation) => {
    try {
      clearMessages()
      const sessionId = conversation.session_id || null

      if (sessionId) {
        currentSessionId.value = sessionId
        await loadConversationMessages(sessionId)
        showAbilityPanel.value = false
        showAbilityButton.value = false
        hasUsedAbilityEntryInSession.value = true
      } else {
        if (conversation.agent_id && agents.value.length > 0) {
          const agent = agents.value.find(a => a.id === conversation.agent_id)
          if (agent) {
            await selectAgent(agent)
          } else {
            await selectAgent(agents.value[0])
          }
        }
        if (conversation.messages && conversation.messages.length > 0) {
          messages.value = conversation.messages.map(msg => ({
            ...msg,
            agent_id: msg.agent_id || conversation.agent_id
          }))
          rebuildMessageIdIndexMap()
        }
        currentSessionId.value = sessionId
        showAbilityButton.value = true
      }

      nextTick(() => {
        shouldAutoScroll.value = true
        scrollToBottom(true)
      })
    } catch (error) {
      toast.error(t('chat.loadConversationError'))
    }
  }

  const copyToClipboard = (text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text)
    }
    return new Promise((resolve, reject) => {
      try {
        const textArea = document.createElement('textarea')
        textArea.value = text
        textArea.style.position = 'fixed'
        textArea.style.left = '-9999px'
        document.body.appendChild(textArea)
        textArea.focus()
        textArea.select()
        const successful = document.execCommand('copy')
        document.body.removeChild(textArea)
        if (successful) resolve()
        else reject(new Error('execCommand copy failed'))
      } catch (err) {
        reject(err)
      }
    })
  }

  const handleShare = () => {
    if (!currentSessionId.value) {
      toast.error(t('chat.shareNoSession') || 'No active session to share')
      return
    }
    const rawBase = (import.meta.env?.BASE_URL || '/').toString()
    const base = rawBase.endsWith('/') ? rawBase : `${rawBase}/`
    const shareUrl = `${window.location.origin}${base}share/${currentSessionId.value}`
    copyToClipboard(shareUrl).then(() => {
      toast.success(t('chat.shareSuccess') || 'Share link copied to clipboard')
    }).catch(() => {
      toast.error(t('chat.shareFailed') || 'Failed to copy link')
    })
  }
  const persistRunningSessionOnLeaveChat = (includeInSidebar = true) => {
    // 如果页面正在生成回复，中断它
    if (isLoading.value && abortControllerRef.value) {
      abortControllerRef.value.abort()
      abortControllerRef.value = null
    }
    // 注意：进行中的会话状态现在由服务端通过 SSE 同步
    // 前端不再主动管理 activeSessions 状态
  }

  const openAbilityPanel = async ({ forceRefresh = false } = {}) => {
    if (!selectedAgent.value) return
    const agentId = selectedAgent.value.id
    const sessionId = currentSessionId.value

    showAbilityPanel.value = true
    abilityError.value = null

    const cache = abilityCacheByAgentGlobal.value[agentId]
    if (!forceRefresh && cache && Array.isArray(cache)) {
      abilityItems.value = cache
      return
    }

    abilityLoading.value = true
    try {
      const items = await agentAPI.getAgentAbilities({
        agentId,
        sessionId,
        context: {},
        language: language?.value
      })
      abilityItems.value = items || []
      abilityCacheByAgentGlobal.value = {
        ...abilityCacheByAgentGlobal.value,
        [agentId]: abilityItems.value
      }
    } catch (err) {
      console.error('加载 Agent 能力失败:', err)
      abilityError.value = err?.message || t('chat.abilities.error') || '获取能力列表失败'
    } finally {
      abilityLoading.value = false
    }
  }

  const closeAbilityPanel = () => {
    showAbilityPanel.value = false
  }

  const retryAbilityFetch = () => {
    openAbilityPanel({ forceRefresh: true })
  }

  const onAbilityCardClick = (item) => {
    if (!item || !item.promptText) return
    abilityPresetInput.value = item.promptText
  }

  useChatLifecycle({
    props,
    route,
    currentSessionId,
    currentTraceId,
    makeTraceId: (sessionId) => SparkMD5.hash(sessionId),
    loadAgents,
    handleActiveSessionsUpdated,
    handleSessionLoad: async (sessionId) => {
      // 切换会话时重置工作台状态
      workbenchStore.resetState()
      panelStore.closeAll()
      console.log('[ChatPage] Reset workbench state before loading session:', sessionId)
      await handleSessionLoad(sessionId)
    },
    createSession,
    clearScrollTimer,
    agents,
    restoreSelectedAgent,
    loadConversationData,
    resetChat,
    messages,
    shouldAutoScroll,
    scrollToBottom,
    activeSubSessionId,
    isLoading,
    isHistoryLoading,
    onLeaveChatPage: persistRunningSessionOnLeaveChat,
    startSSESync,
    stopSSESync
  })  
  
  // 监听工作台 items 变化，当有新 item 且处于实时模式时，自动打开工作台
  watch(() => workbenchStore.filteredItems.length, (newLength, oldLength) => {
    if (newLength > oldLength && workbenchStore.isRealtime) {
      // 有新 item 添加且处于实时模式，自动打开工作台
      if (!panelStore.showWorkbench) {
        console.log('[ChatPage] New workbench item added, auto-opening workbench')
        panelStore.openWorkbench()
      }
    }
  })

  // 监听 session id 变化，当 session id 变化或变为 null 时重置工作台
watch(() => currentSessionId.value, (newSessionId, oldSessionId) => {
  console.log('[ChatPage] Session ID changed:', oldSessionId, '->', newSessionId)
  if (newSessionId !== oldSessionId) {
    // Session ID 变化，重置工作台
    workbenchStore.resetState()
    if (newSessionId) {
      workbenchStore.setSessionId(newSessionId)
    }
    // 如果 session id 为 null，关闭工作台弹窗
    if (!newSessionId) {
      panelStore.closeAll()
      console.log('[ChatPage] Session ID is null, closed workbench')
    }
    }
  })

  watch(() => selectedAgentId.value, () => {
    showAbilityPanel.value = false
  })


  return {
    t,
    agents,
    selectedAgent,
    selectedAgentId,
    config,
    messagesListRef,
    messagesEndRef,
    showWorkspace,
    showLoadingBubble,
    filteredMessages,
    isLoading,
    isCurrentSessionLoading,
    currentSessionId,
    handleAgentChange,
    togglePanel,
    openWorkbench,
    handleShare,
    handleScroll,
    handleSendMessage,
    stopGeneration,
    activeSubSessionId,
    subSessionMessages,
    handleCloseSubSession,
    handleOpenSubSession,
    downloadWorkspaceFile,
    workspaceFiles,
    isWorkspaceLoading,
    downloadFile,
    deleteFile,
    refreshWorkspace,
    updateConfig,
    abilityItems,
    abilityLoading,
    abilityError,
    showAbilityPanel,
    abilityPresetInput,
    showAbilityButton,
    hasUsedAbilityEntryInSession,
    openAbilityPanel,
    closeAbilityPanel,
    retryAbilityFetch,
    onAbilityCardClick,
    submitEditedLastUserMessage
  }
}
