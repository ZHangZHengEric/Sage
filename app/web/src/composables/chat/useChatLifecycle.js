import { onMounted, onUnmounted, watch } from 'vue'

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
  isHistoryLoading,
  onLeaveChatPage
}) => {
  const handleBeforeUnload = () => {
    if (typeof onLeaveChatPage === 'function') {
      // 页面刷新时保存状态，但不显示在侧边栏（除非之前已经显示）
      // 这里我们传递 false，意味着如果是仅因为刷新而触发的保存，
      // 该会话不会被强制加入侧边栏列表。
      onLeaveChatPage(false)
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
      window.addEventListener('active-sessions-updated', handleActiveSessionsUpdated)
      window.addEventListener('beforeunload', handleBeforeUnload)
    }
    await loadAgents()
    const routeSessionId = route.query.session_id
    if (routeSessionId) {
      await handleSessionLoad(routeSessionId)
    } else {
      createSession()
    }
  })

  onUnmounted(() => {
    if (typeof onLeaveChatPage === 'function') {
      onLeaveChatPage(true)
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('user-updated', loadAgents)
      window.removeEventListener('active-sessions-updated', handleActiveSessionsUpdated)
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
    clearScrollTimer()
  })

  watch(() => agents.value, async (newAgents) => {
    if (newAgents && newAgents.length > 0) {
      await restoreSelectedAgent(newAgents)
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
    if (oldName === 'Chat' && newName !== 'Chat') {
      if (typeof onLeaveChatPage === 'function') {
        onLeaveChatPage(true)
      }
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
