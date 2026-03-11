import { onMounted, onUnmounted, watch } from 'vue'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { usePanelStore } from '@/stores/panel.js'

export const useChatLifecycle = ({
  props,
  route,
  currentSessionId,
  currentTraceId,
  makeTraceId,
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
  isHistoryLoading
}) => {
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
      window.addEventListener('active-sessions-updated', handleActiveSessionsUpdated)
    }
    await loadAgents()
    const routeSessionId = route.query.session_id
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
  })

  onUnmounted(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('user-updated', loadAgents)
      window.removeEventListener('active-sessions-updated', handleActiveSessionsUpdated)
    }
    clearScrollTimer()
  })

  watch(() => agents.value, (newAgents) => {
    if (newAgents && newAgents.length > 0) {
      restoreSelectedAgent(newAgents)
    }
  })

  watch(() => props.selectedConversation, async (newConversation) => {
    if (newConversation && agents.value.length > 0) {
      await loadConversationData(newConversation)
    } else if (!newConversation) {
      resetChat()
    }
  }, { immediate: false })

  watch(() => route.query.session_id, (newSessionId) => {
    if (newSessionId === currentSessionId.value) return
    if (newSessionId) {
      handleSessionLoad(newSessionId)
    } else {
      resetChat()
    }
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
