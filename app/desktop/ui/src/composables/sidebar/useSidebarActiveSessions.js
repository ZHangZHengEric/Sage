import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useChatActiveSessionCache } from '@/composables/chat/useChatActiveSessionCache'

export const useSidebarActiveSessions = ({
  route,
  onSessionClick
}) => {
  const { 
    activeSessions, 
    removeSessionFromCache,
    startSSESync,
    stopSSESync
  } = useChatActiveSessionCache()

  onMounted(() => {
    startSSESync()
  })

  onUnmounted(() => {
    stopSSESync()
  })

  const activeSessionSelectionEnabled = ref(false)

  const activeSessionItems = computed(() =>
    Object.entries(activeSessions.value || {})
      .filter(([, meta]) => !!meta && !!meta.include_in_sidebar)
      .sort(([, a], [, b]) => (b?.lastUpdate || 0) - (a?.lastUpdate || 0))
      .map(([sessionId, meta]) => {
        // 处理 user_input 可能是对象的情况
        let userInput = meta?.user_input || ''
        if (userInput && typeof userInput === 'object') {
          userInput = userInput.text || userInput.content || userInput.message || JSON.stringify(userInput)
        }
        // 处理 title 可能是对象的情况
        let title = meta?.title || ''
        if (title && typeof title === 'object') {
          title = title.text || title.content || title.message || JSON.stringify(title)
        }
        return {
          id: sessionId,
          sessionId,
          sessionStatus: meta?.status === 'completed' ? 'completed' : 'running',
          rawName: (String(userInput).replace(/^<skill>.*?<\/skill>\s*/, '').split('\n')[0].trim()) || String(title) || `会话 ${sessionId.slice(-8)}`,
          url: 'Chat',
          isInternal: true,
          query: { session_id: sessionId }
        }
      })
  )

  const isActiveSessionCurrent = (session) => {
    if (!activeSessionSelectionEnabled.value) return false
    return route.name === 'Chat' && route.query.session_id === session?.query?.session_id
  }

  const handleActiveSessionClick = (session) => {
    activeSessionSelectionEnabled.value = true
    onSessionClick(session)
    if (session.sessionStatus === 'completed') {
      removeSessionFromCache(session.sessionId)
    }
  }

  const disableActiveSessionSelection = () => {
    activeSessionSelectionEnabled.value = false
  }

  return {
    activeSessionItems,
    handleActiveSessionClick,
    isActiveSessionCurrent,
    disableActiveSessionSelection
  }
}
