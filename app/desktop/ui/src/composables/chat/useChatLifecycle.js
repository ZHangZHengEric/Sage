import { onActivated, onMounted, onUnmounted, watch } from 'vue'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { usePanelStore } from '@/stores/panel.js'

export const useChatLifecycle = ({
  props,
  route,
  router,
  currentSessionId,
  currentTraceId,
  makeTraceId,
  loadAgents,
  handleActiveSessionsUpdated,
  handleSessionLoad,
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
}) => {
  const doSwitchToNewSession = switchToNewSession || resetChat

  const consumeReloadNewChatQuery = async () => {
    const reloadToken = route.query.reload_new_chat
    if (!reloadToken || route.name !== 'Chat' || route.query.session_id) return

    resetChat()

    if (router) {
      await router.replace({
        name: 'Chat',
        query: {
          ...route.query,
          reload_new_chat: undefined
        }
      })
    }
  }

  watch(currentSessionId, (newVal) => {
    if (newVal) {
      currentTraceId.value = makeTraceId(newVal)
    } else {
      currentTraceId.value = null
    }
  })

  watch(() => props.chatResetToken, (newVal) => {
    if (newVal) resetChat()
  })

  onMounted(async () => {
    if (typeof window !== 'undefined') {
      window.addEventListener('user-updated', loadAgents)
      window.addEventListener('agents-updated', loadAgents)
      window.addEventListener('active-sessions-updated', handleActiveSessionsUpdated)
    }
    await loadAgents()
    const routeSessionId = route.query.session_id

    // 优先从 URL 参数获取 agent
    const urlAgentId = route.query.agent
    // 从 localStorage 获取，但只使用一次（用于从 AgentCard 跳转的场景）
    const storageAgentId = localStorage.getItem('selectedAgentId')
    const targetAgentId = urlAgentId || storageAgentId

    console.log('[ChatLifecycle] onMounted - urlAgentId:', urlAgentId)
    console.log('[ChatLifecycle] onMounted - storageAgentId:', storageAgentId)
    console.log('[ChatLifecycle] onMounted - targetAgentId:', targetAgentId)
    console.log('[ChatLifecycle] onMounted - agents count:', agents.value?.length)

    // 如果 URL 或 localStorage 中有 agent 且 agents 已加载，立即选择
    if (targetAgentId && agents.value.length > 0) {
      const targetAgent = agents.value.find(a => a.id === targetAgentId)
      console.log('[ChatLifecycle] onMounted - found targetAgent:', !!targetAgent)
      if (targetAgent) {
        // 使用 forceConfigUpdate=true 确保配置被更新
        selectAgent(targetAgent, true)
        console.log('[ChatLifecycle] onMounted - Auto-selected agent:', targetAgentId)
      }
    } else if (agents.value.length > 0) {
      // 如果没有指定 agent，但有可用的 agents，自动选择第一个（默认 agent）
      console.log('[ChatLifecycle] onMounted - No targetAgentId, selecting first agent')
      restoreSelectedAgent(agents.value)
    }

    // 清除 URL 中的 agent 参数和 localStorage（只使用一次）
    if (router && urlAgentId) {
      router.replace({
        query: { ...route.query, agent: undefined }
      })
    }
    // 清除 localStorage 中的 selectedAgentId，避免影响后续的"新对话"操作
    if (storageAgentId) {
      localStorage.removeItem('selectedAgentId')
      console.log('[ChatLifecycle] Cleared selectedAgentId from localStorage')
    }

    if (routeSessionId) {
      await handleSessionLoad(routeSessionId)
    } else {
      // 新会话时重置工作台状态并关闭面板
      const workbenchStore = useWorkbenchStore()
      const panelStore = usePanelStore()
      workbenchStore.resetState() // 重置所有状态（包括实时模式）
      panelStore.closeAll()
      console.log('[ChatLifecycle] Reset workbench state and closed panels for new session')
      createSession()
    }

    await consumeReloadNewChatQuery()
  })

  onUnmounted(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('user-updated', loadAgents)
      window.removeEventListener('agents-updated', loadAgents)
      window.removeEventListener('active-sessions-updated', handleActiveSessionsUpdated)
    }
    clearScrollTimer()
  })

  onActivated(() => {
    void loadAgents()
  })

  watch(() => agents.value, (newAgents) => {
    console.log('[ChatLifecycle] agents.value changed, count:', newAgents?.length)
    if (newAgents && newAgents.length > 0) {
      const routeAgentId = route.query.agent
      console.log('[ChatLifecycle] routeAgentId from URL:', routeAgentId)
      console.log('[ChatLifecycle] localStorage selectedAgentId:', localStorage.getItem('selectedAgentId'))
      // 如果 URL 中有 agent 参数，优先选择该 Agent
      if (routeAgentId) {
        const targetAgent = newAgents.find(a => a.id === routeAgentId)
        console.log('[ChatLifecycle] Found targetAgent in agents:', !!targetAgent)
        if (targetAgent) {
          console.log('[ChatLifecycle] Calling selectAgent for:', routeAgentId)
          selectAgent(targetAgent)
          console.log('[ChatLifecycle] Auto-selected agent from URL:', routeAgentId)
          // 清除 URL 中的 agent 参数，避免刷新时重复选择
          if (router) {
            router.replace({
              query: { ...route.query, agent: undefined }
            })
          }
          return
        } else {
          console.log('[ChatLifecycle] Target agent not found in agents list, available IDs:', newAgents.map(a => a.id))
        }
      }
      console.log('[ChatLifecycle] No routeAgentId, calling restoreSelectedAgent')
      restoreSelectedAgent(newAgents)
    }
  })

  watch(() => props.selectedConversation, async (newConversation) => {
    if (newConversation && agents.value.length > 0) {
      await loadConversationData(newConversation)
    } else if (!newConversation) {
      doSwitchToNewSession()
    }
  }, { immediate: false })

  watch(() => route.query.session_id, (newSessionId) => {
    if (newSessionId === currentSessionId.value) return
    if (newSessionId) {
      handleSessionLoad(newSessionId)
    } else {
      doSwitchToNewSession()
    }
  })

  watch(() => route.query.reload_new_chat, async (newVal, oldVal) => {
    if (!newVal || newVal === oldVal) return
    await consumeReloadNewChatQuery()
  })

  watch(() => route.name, (newName, oldName) => {
    // 路由变化时清理工作台
    if (oldName === 'Chat' && newName !== 'Chat') {
       // do nothing
    }
  })

  watch(() => messages.value.length, () => {
    if (shouldAutoScroll.value) {
      scrollToBottom()
    }
  })

  watch(() => {
    const list = messages.value || []
    if (list.length === 0) return ''
    const lastMsg = list[list.length - 1]
    const toolCallSignature = (lastMsg.tool_calls || [])
      .map(call => `${call.id || ''}:${call.function?.name || ''}:${call.function?.arguments || ''}`)
      .join('|')
    return `${list.length}|${lastMsg.message_id || ''}|${lastMsg.role || ''}|${lastMsg.tool_call_id || ''}|${toolCallSignature}`
  }, () => {
    const newMessages = messages.value
    if (!newMessages || newMessages.length === 0) return
    const lastMsg = newMessages[newMessages.length - 1]
    if (lastMsg.role === 'assistant' && lastMsg.tool_calls) {
      const delegateCall = lastMsg.tool_calls.find(c => c.function?.name === 'sys_delegate_task')
      if (delegateCall) {
        try {
          const args = typeof delegateCall.function.arguments === 'string'
            ? JSON.parse(delegateCall.function.arguments)
            : delegateCall.function.arguments
          const sessionId = args.tasks?.[0]?.session_id
          if (sessionId && activeSubSessionId.value !== sessionId) {
            if (isLoading.value && !isHistoryLoading.value) {
              activeSubSessionId.value = sessionId
            }
          }
        } catch (e) {
          console.error('Failed to parse sys_delegate_task arguments:', e)
        }
      }
    }
    if (lastMsg.role === 'tool' && activeSubSessionId.value) {
      const toolCallId = lastMsg.tool_call_id
      for (let i = newMessages.length - 2; i >= 0; i--) {
        const msg = newMessages[i]
        if (msg.role === 'assistant' && msg.tool_calls) {
          const matchingCall = msg.tool_calls.find(c => c.id === toolCallId)
          if (matchingCall && matchingCall.function?.name === 'sys_delegate_task') {
            try {
              const args = typeof matchingCall.function.arguments === 'string'
                ? JSON.parse(matchingCall.function.arguments)
                : matchingCall.function.arguments
              const sessionId = args.tasks?.[0]?.session_id
              if (sessionId === activeSubSessionId.value) {
                activeSubSessionId.value = null
              }
            } catch (e) {
              console.error('Failed to check tool result for auto-close:', e)
            }
            break
          }
        }
      }
    }
  })
}
