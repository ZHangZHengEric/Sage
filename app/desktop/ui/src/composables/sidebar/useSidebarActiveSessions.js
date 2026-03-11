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
      .map(([sessionId, meta]) => ({
        id: sessionId,
        sessionId,
        sessionStatus: meta?.status === 'completed' ? 'completed' : 'running',
        rawName: (String(meta?.user_input || '').replace(/^<skill>.*?<\/skill>\s*/, '').split('\n')[0].trim()) || meta?.title || `会话 ${sessionId.slice(-8)}`,
        url: 'Chat',
        isInternal: true,
        query: { session_id: sessionId }
      }))
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
