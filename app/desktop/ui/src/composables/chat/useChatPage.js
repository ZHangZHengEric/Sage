import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import SparkMD5 from 'spark-md5'
import { useLanguage } from '@/utils/i18n.js'
import { chatAPI } from '@/api/chat.js'
import { agentAPI } from '@/api/agent.js'
import { useChatActiveSessionCache } from '@/composables/chat/useChatActiveSessionCache.js'
import { useChatScroll } from '@/composables/chat/useChatScroll.js'
import { useChatStream } from '@/composables/chat/useChatStream.js'
import { useChatLifecycle } from '@/composables/chat/useChatLifecycle.js'
import { useChatAgentConfig } from '@/composables/chat/useChatAgentConfig.js'
import { useChatWorkspace } from '@/composables/chat/useChatWorkspace.js'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { usePanelStore } from '@/stores/panel.js'

// 全局按 Agent 缓存能力结果，在整个应用生命周期内共享
const abilityCacheByAgentGlobal = ref({})

export const useChatPage = (props) => {
  const { t, language } = useLanguage()
  const route = useRoute()
  const router = useRouter()

  const {
    activeSessions,
    handleActiveSessionsUpdated,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    removeSessionFromCache,
    deriveSessionTitle,
    startSSESync,
    stopSSESync
  } = useChatActiveSessionCache()
  
  onMounted(() => {
    startSSESync()
  })

  const {
    messagesListRef,
    messagesEndRef,
    shouldAutoScroll,
    scrollToBottom,
    handleScroll,
    clearScrollTimer
  } = useChatScroll()

  // 使用 panelStore 管理面板状态
  const panelStore = usePanelStore()
  const workbenchStore = useWorkbenchStore()

  const showSettings = ref(false)
  const currentTraceId = ref(null)

  // 能力面板相关状态
  const abilityItems = ref([])
  const abilityLoading = ref(false)
  const abilityError = ref(null)
  const showAbilityPanel = ref(false)
  const abilityPresetInput = ref('')
  const showAbilityButton = ref(true)
  const hasUsedAbilityEntryInSession = ref(false)
  /** 新会话时递增，用于让弹幕组件重置（与「你能做什么」逻辑一致：关闭后在新会话再出现） */
  const danmakuResetTrigger = ref(0)
  /** 当前为历史会话时为 true，弹幕不展示（与「你能做什么」逻辑一致） */
  const isViewingHistorySession = ref(false)
  /** 用户点击弹幕关闭键时为 true，切换页面再回来不重置弹幕（仍保持关闭） */
  const danmakuClosedByUser = ref(false)
  /** 进入历史会话前「你能做什么」是否还在显示，从历史回新会话时用于恢复 */
  const abilityButtonVisibleBeforeHistory = ref(true)
  /** 进入历史会话前能力面板是否打开（含加载中），从历史回新会话时恢复，避免「点你能做什么→加载中→进历史→回来」动画/结果丢失 */
  const abilityPanelOpenBeforeHistory = ref(false)

  // 打开工作台（统一方法）
  const openWorkbench = (options = {}) => {
    const { toolCallId = null, realtime = true } = options

    // 打开工作台
    panelStore.openWorkbench()

    // 设置实时模式
    if (realtime) {
      workbenchStore.setRealtime(true)
    }

    // 如果指定了 toolCallId，跳转到对应项
    if (toolCallId) {
      const filteredItems = workbenchStore.filteredItems
      const index = filteredItems.findIndex(item =>
        item.type === 'tool_call' && item.data.id === toolCallId
      )
      if (index !== -1) {
        workbenchStore.setCurrentIndex(index)
        workbenchStore.setRealtime(false)
      }
    }
  }

  // 切换面板（互斥）
  const togglePanel = (panel) => {
    if (panel === 'workbench') {
      // 使用统一方法打开工作台
      openWorkbench()
    } else if (panel === 'workspace') {
      if (panelStore.activePanel === 'workspace') {
        panelStore.closeAll()
      } else {
        panelStore.openWorkspace()
        refreshWorkspace()
      }
      // 打开/切换其它面板时关闭能力面板
      showAbilityPanel.value = false
    } else if (panel === 'settings') {
      if (panelStore.activePanel === 'settings') {
        panelStore.closeAll()
      } else {
        panelStore.openSettings()
      }
      // 打开/切换其它面板时关闭能力面板
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
    const workbenchStore = useWorkbenchStore()
    workbenchStore.clearItems()
    workbenchStore.setSessionId(sessionId)
    console.log('[ChatPage] Cleared workbench for session:', sessionId)

    const res = await chatAPI.getConversationMessages(sessionId)
    if (!res || !res.messages) return
    const normalizedMessages = (res.messages || []).map(msg => ({
      ...msg,
      session_id: msg.session_id || sessionId
    }))

    messages.value = normalizedMessages
    rebuildMessageIdIndexMap()

    // 只有在有消息且有工作台 item 时，才自动打开工作台
    if (normalizedMessages.length > 0 && workbenchStore.filteredItems.length > 0) {
      openWorkbench({ realtime: true })
    }

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
    // 不要强制重置 shouldAutoScroll，也不要强制滚动
    // 只有当 shouldAutoScroll 为 true 时（即用户在底部），scrollToBottom 才会执行滚动
    nextTick(() => scrollToBottom())
  }

  const addUserMessage = (content, sessionId, multimodalContent = null) => {
    // 如果有多模态内容，使用数组格式；否则使用纯文本
    const messageContent = multimodalContent && multimodalContent.length > 0
      ? multimodalContent
      : content.trim()

    const userMessage = {
      role: 'user',
      content: messageContent,
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
    deleteFile,
    clearTaskAndWorkspace,
    refreshWorkspace
  } = useChatWorkspace({
    t,
    toast,
    currentSessionId,
    selectedAgentId
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
    isHistoryLoading,
    removeSessionFromCache
  })

  const showLoadingBubble = computed(() => !!isLoading.value)

  const resetChat = () => {
    clearCurrentStreamViewState()
    clearMessages()
    clearTaskAndWorkspace()
    // 重置工作台所有状态
    workbenchStore.resetState()
    console.log('[ChatPage] Reset workbench state for new session')
    // 关闭工作台 panel
    panelStore.closeAll()
    console.log('[ChatPage] Closed panel for new session')
    // 新会话：重置能力入口状态
    showAbilityPanel.value = false
    abilityPresetInput.value = ''
    abilityError.value = null
    hasUsedAbilityEntryInSession.value = false
    showAbilityButton.value = true
    isViewingHistorySession.value = false
    danmakuClosedByUser.value = false
    danmakuResetTrigger.value += 1
    createSession()
  }

  /** 从历史点回新会话：恢复「你能做什么」与弹幕仅当进入历史前未关；已关则保持不显示；并恢复能力面板打开状态（含加载中/已加载结果） */
  const switchToNewSession = () => {
    clearCurrentStreamViewState()
    clearMessages()
    clearTaskAndWorkspace()
    // 从历史回新会话：重置工作台状态并关闭面板（避免工作台带入新会话）
    workbenchStore.resetState()
    panelStore.closeAll()
    isViewingHistorySession.value = false
    showAbilityButton.value = abilityButtonVisibleBeforeHistory.value
    if (abilityButtonVisibleBeforeHistory.value) hasUsedAbilityEntryInSession.value = false
    if (!danmakuClosedByUser.value) danmakuResetTrigger.value += 1
    // 若进历史前能力面板是打开的（含加载中），回来时重新打开，避免加载动画/结果丢失
    showAbilityPanel.value = abilityPanelOpenBeforeHistory.value
    createSession()
  }

  const loadConversationData = async (conversation) => {
    try {
      clearMessages()
      if (conversation.agent_id && agents.value.length > 0) {
        const agent = agents.value.find(a => a.id === conversation.agent_id)
        if (agent) {
          selectAgent(agent)
        }
      }
      if (conversation.messages && conversation.messages.length > 0) {
        messages.value = conversation.messages
        rebuildMessageIdIndexMap()
      }
      currentSessionId.value = conversation.session_id || null
      // 进入历史前保存「你能做什么」与能力面板状态，从历史回新会话时据此恢复
      abilityButtonVisibleBeforeHistory.value = showAbilityButton.value
      abilityPanelOpenBeforeHistory.value = showAbilityPanel.value
      // 加载历史会话时，不展示新手引导入口与弹幕
      showAbilityPanel.value = false
      showAbilityButton.value = false
      hasUsedAbilityEntryInSession.value = true
      isViewingHistorySession.value = true
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
    const shareUrl = `${window.location.origin}/share/${currentSessionId.value}`
    copyToClipboard(shareUrl).then(() => {
      toast.success(t('chat.shareSuccess') || 'Share link copied to clipboard')
    }).catch(() => {
      toast.error(t('chat.shareFailed') || 'Failed to copy link')
    })
  }

  const persistRunningSessionOnLeaveChat = (includeInSidebar = true) => {
    if (isLoading.value && abortControllerRef.value) {
      abortControllerRef.value.abort()
      abortControllerRef.value = null
    }

    const sessionId = currentSessionId.value
    if (!sessionId) return
    const meta = activeSessions.value?.[sessionId]
    if (meta?.status === 'running') {
      const firstUserMessage = (messages.value || []).find(item =>
        item?.session_id === sessionId && item?.role === 'user' && String(item?.content || '').trim()
      )
      if (firstUserMessage) {
        const firstUserInput = String(firstUserMessage.content || '')
          .replace(/^<skill>.*?<\/skill>\s*/, '')
          .trim()
        if (firstUserInput) {
          updateActiveSession(sessionId, true, deriveSessionTitle(firstUserInput), firstUserInput, false)
        }
      }
      persistRunningSessionToCache(sessionId, includeInSidebar)
      return
    }
    if (meta?.status === 'completed') {
      removeSessionFromCache(sessionId)
    }
  }

  // 能力面板：打开 / 关闭 / 重试 / 选择卡片
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
    router,
    currentSessionId,
    currentTraceId,
    makeTraceId: (sessionId) => SparkMD5.hash(sessionId),
    loadAgents,
    handleActiveSessionsUpdated,
    handleSessionLoad: async (sessionId) => {
      // 切换会话时重置工作台状态
      workbenchStore.resetState()
      panelStore.closeAll()
      // 进入历史前保存「你能做什么」与能力面板状态，从历史回新会话时恢复
      abilityButtonVisibleBeforeHistory.value = showAbilityButton.value
      abilityPanelOpenBeforeHistory.value = showAbilityPanel.value
      // 通过 session_id 进入的均为历史会话，不展示「你能做什么」与弹幕
      showAbilityPanel.value = false
      showAbilityButton.value = false
      hasUsedAbilityEntryInSession.value = true
      isViewingHistorySession.value = true
      console.log('[ChatPage] Reset workbench state before loading session:', sessionId)
      await handleSessionLoad(sessionId)
    },
    createSession,
    clearScrollTimer,
    agents,
    selectAgent,
    restoreSelectedAgent,
    loadConversationData,
    resetChat,
    switchToNewSession,
    messages,
    shouldAutoScroll,
    scrollToBottom,
    activeSubSessionId,
    isLoading,
    isHistoryLoading
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
      // 如果 session id 为 null，关闭工作台弹窗
      if (!newSessionId) {
        panelStore.closeAll()
        console.log('[ChatPage] Session ID is null, closed workbench')
      }
    }
  })
  
  // 监听 Agent 变更时关闭能力面板，但保留缓存
  watch(() => selectedAgentId.value, () => {
    showAbilityPanel.value = false
  })

  onUnmounted(() => {
    stopSSESync()
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
    showLoadingBubble,
    filteredMessages,
    isLoading,
    isCurrentSessionLoading,
    handleAgentChange,
    handleWorkspacePanel,
    togglePanel,
    openWorkbench,
    handleShare,
    handleScroll,
    handleSendMessage,
    stopGeneration,
    currentSessionId,
    activeSubSessionId,
    subSessionMessages,
    handleCloseSubSession,
    handleOpenSubSession,
    downloadWorkspaceFile,
    workspaceFiles,
    downloadFile,
    deleteFile,
    updateConfig,
    refreshWorkspace,
    // 能力面板相关
    abilityItems,
    abilityLoading,
    abilityError,
    showAbilityPanel,
    abilityPresetInput,
    showAbilityButton,
    hasUsedAbilityEntryInSession,
    danmakuResetTrigger,
    isViewingHistorySession,
    danmakuClosedByUser,
    openAbilityPanel,
    closeAbilityPanel,
    retryAbilityFetch,
    onAbilityCardClick
  }
}
