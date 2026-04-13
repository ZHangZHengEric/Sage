import { ref, computed, onMounted, onUnmounted } from 'vue'

export const useSidebarActiveSessions = ({
  route,
  onSessionClick
}) => {
  const activeSessionSelectionEnabled = ref(false)
  const activeSessions = ref({})

  const loadActiveSessions = () => {
    try {
      activeSessions.value = JSON.parse(localStorage.getItem('activeSessions') || '{}')
    } catch (e) {
      activeSessions.value = {}
    }
  }

  const activeSessionItems = computed(() =>
    Object.entries(activeSessions.value || {})
      .filter(([, meta]) => !!meta && meta.include_in_sidebar && (meta.status === 'running' || meta.status === 'interrupting'))
      .sort(([, a], [, b]) => (b?.lastUpdate || 0) - (a?.lastUpdate || 0))
      .map(([sessionId, meta]) => ({
        id: sessionId,
        sessionId,
        sessionStatus: meta.status || 'running',
        rawName: meta?.title || `会话 ${sessionId.slice(-8)}`,
        url: 'Chat',
        isInternal: true,
        query: { session_id: sessionId }
      }))
  )

  const persistActiveSessions = () => {
    localStorage.setItem('activeSessions', JSON.stringify(activeSessions.value))
  }

  const removeActiveSession = (sessionId) => {
    if (!sessionId || !activeSessions.value[sessionId]) return
    delete activeSessions.value[sessionId]
    persistActiveSessions()
  }

  const isActiveSessionCurrent = (session) => {
    if (!activeSessionSelectionEnabled.value) return false
    return route.name === 'Chat' && route.query.session_id === session?.query?.session_id
  }

  const handleActiveSessionClick = (session) => {
    activeSessionSelectionEnabled.value = true
    onSessionClick(session)
  }

  const disableActiveSessionSelection = () => {
    activeSessionSelectionEnabled.value = false
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      window.addEventListener('active-sessions-updated', loadActiveSessions)
      loadActiveSessions()
    }
  })

  onUnmounted(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('active-sessions-updated', loadActiveSessions)
    }
  })

  return {
    activeSessionItems,
    handleActiveSessionClick,
    isActiveSessionCurrent,
    disableActiveSessionSelection
  }
}
