import { ref, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import SparkMD5 from 'spark-md5'
import { useLanguage } from '@/utils/i18n.js'
import { chatAPI } from '@/api/chat.js'
import { useChatActiveSessionCache } from '@/composables/chat/useChatActiveSessionCache.js'
import { useChatScroll } from '@/composables/chat/useChatScroll.js'
import { injectFirstUserMessageIfNeeded } from '@/composables/chat/chatMessageUtils.js'
import { useChatStream } from '@/composables/chat/useChatStream.js'
import { useChatLifecycle } from '@/composables/chat/useChatLifecycle.js'
import { useChatAgentConfig } from '@/composables/chat/useChatAgentConfig.js'
import { useChatWorkspace } from '@/composables/chat/useChatWorkspace.js'

export const useChatPage = (props) => {
  const { t } = useLanguage()
  const route = useRoute()
  const router = useRouter()

  const {
    activeSessions,
    handleActiveSessionsUpdated,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    persistRunningSessionToCache,
    removeSessionFromCache,
    deriveSessionTitle
  } = useChatActiveSessionCache()

  const {
    messagesListRef,
    messagesEndRef,
    shouldAutoScroll,
    scrollToBottom,
    handleScroll,
    clearScrollTimer
  } = useChatScroll()
  const showSettings = ref(false)
  const showToolDetails = ref(false)
  const currentTraceId = ref(null)
  const selectedToolExecution = ref(null)
  const toolResult = ref(null)

  const openTraceDetails = () => {
    const baseUrl = import.meta.env.VITE_SAGE_TRACE_WEB_URL
    if (!baseUrl || !currentTraceId.value) {
      if (!baseUrl) toast.error('Jaeger URL not configured')
      if (!currentTraceId.value) toast.error('No trace ID available')
      return
    }
    window.open(`${baseUrl}/trace/${currentTraceId.value}`, '_blank')
  }

  const messages = ref([])
  const messageIdIndexMap = ref(new Map())
  const messageChunks = ref(new Map())
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
    const res = await chatAPI.getConversationMessages(sessionId)
    if (!res || !res.messages) return
    const normalizedMessages = (res.messages || []).map(msg => ({
      ...msg,
      session_id: msg.session_id || sessionId
    }))
    const activeMeta = activeSessions.value[sessionId]
    const shouldInjectFirstUserMessage =
      activeMeta?.status === 'running' &&
      !!activeMeta?.user_input &&
      (normalizedMessages.length === 0 || normalizedMessages[0]?.role !== 'user')
    if (shouldInjectFirstUserMessage) {
      normalizedMessages.unshift({
        role: 'user',
        content: activeMeta.user_input,
        message_id: `pending_user_${sessionId}`,
        type: 'USER',
        session_id: sessionId,
        timestamp: Date.now()
      })
    }
    messages.value = normalizedMessages
    rebuildMessageIdIndexMap()
    if (res.conversation_info?.agent_id) {
      const agent = agents.value.find(a => a.id === res.conversation_info.agent_id)
      if (agent) {
        selectAgent(agent)
      }
    }
    if (res.conversation_info && activeSessions.value[sessionId]?.status === 'running') {
      updateActiveSession(sessionId, true, res.conversation_info.title)
    }
  }

  const ensureFirstUserMessageForRunningSession = (sessionId) => {
    const activeMeta = activeSessions.value[sessionId]
    const nextMessages = injectFirstUserMessageIfNeeded(messages.value, sessionId, activeMeta)
    if (nextMessages !== messages.value) {
      messages.value = nextMessages
      rebuildMessageIdIndexMap()
    }
  }

  const handleMessage = (messageData) => {
    if (messageData.type === 'stream_end') return
    const messageId = messageData.message_id
    if (messageId && messageIdIndexMap.value.has(messageId)) {
      const targetIndex = messageIdIndexMap.value.get(messageId)
      const existing = messages.value[targetIndex]
      if (!existing) {
        rebuildMessageIdIndexMap()
        return
      }
      let nextMessage
      if (messageData.role === 'tool' || messageData.message_type === 'tool_call_result') {
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
      }
      messages.value.splice(targetIndex, 1, nextMessage)
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
    shouldAutoScroll.value = true
    nextTick(() => scrollToBottom(true))
  }

  const addUserMessage = (content, sessionId) => {
    const userMessage = {
      role: 'user',
      content: content.trim(),
      message_id: Date.now().toString(),
      type: 'USER',
      session_id: sessionId
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
    messageChunks.value = new Map()
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
    handleWorkspacePanel,
    downloadWorkspaceFile,
    downloadFile,
    clearTaskAndWorkspace
  } = useChatWorkspace({
    t,
    toast,
    currentSessionId
  })

  const {
    handleSessionLoad,
    handleSendMessage,
    stopGeneration
  } = useChatStream({
    chatAPI,
    toast,
    t,
    activeSessions,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
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
    ensureFirstUserMessageForRunningSession,
    isHistoryLoading,
    removeSessionFromCache
  })

  const showLoadingBubble = computed(() => !!isLoading.value)

  const resetChat = () => {
    clearCurrentStreamViewState()
    clearMessages()
    clearTaskAndWorkspace()
    createSession()
  }

  const loadConversationData = async (conversation) => {
    try {
      clearMessages()
      if (conversation.agent_id && agents.value.length > 0) {
        const agent = agents.value.find(a => a.id === conversation.agent_id)
        if (agent) {
          selectAgent(agent)
        } else {
          selectAgent(agents.value[0])
        }
      }
      if (conversation.messages && conversation.messages.length > 0) {
        messages.value = conversation.messages
        rebuildMessageIdIndexMap()
      }
      currentSessionId.value = conversation.session_id || null
      nextTick(() => {
        shouldAutoScroll.value = true
        scrollToBottom(true)
      })
    } catch (error) {
      toast.error(t('chat.loadConversationError'))
    }
  }

  const handleToolClick = (toolExecution, result) => {
    selectedToolExecution.value = toolExecution
    toolResult.value = result
    showToolDetails.value = true
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
    const shareUrl = `${window.location.origin}/share/${currentSessionId.value}`
    copyToClipboard(shareUrl).then(() => {
      toast.success(t('chat.shareSuccess') || 'Share link copied to clipboard')
    }).catch(() => {
      toast.error(t('chat.shareFailed') || 'Failed to copy link')
    })
  }

  const persistRunningSessionOnLeaveChat = () => {
    const sessionId = currentSessionId.value
    if (!sessionId) return
    const meta = activeSessions.value?.[sessionId]
    if (meta?.status === 'running') {
      persistRunningSessionToCache(sessionId, true)
      return
    }
    if (meta?.status === 'completed') {
      removeSessionFromCache(sessionId)
    }
  }

  useChatLifecycle({
    props,
    route,
    currentSessionId,
    currentTraceId,
    makeTraceId: (sessionId) => SparkMD5.hash(sessionId),
    loadAgents,
    handleActiveSessionsUpdated,
    handleSessionLoad,
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
    onLeaveChatPage: persistRunningSessionOnLeaveChat
  })

  return {
    t,
    agents,
    selectedAgent,
    selectedAgentId,
    config,
    messagesListRef,
    messagesEndRef,
    showSettings,
    showWorkspace,
    showLoadingBubble,
    filteredMessages,
    isLoading,
    isCurrentSessionLoading,
    handleAgentChange,
    handleWorkspacePanel,
    handleShare,
    openTraceDetails,
    handleScroll,
    handleSendMessage,
    stopGeneration,
    activeSubSessionId,
    subSessionMessages,
    handleCloseSubSession,
    handleOpenSubSession,
    downloadWorkspaceFile,
    handleToolClick,
    workspaceFiles,
    downloadFile,
    updateConfig
  }
}
