import { ref, computed, onMounted, onUnmounted } from 'vue'

export const useSidebarActiveSessions = ({
  route,
  chatAPI,
  onSessionClick
}) => {
  const statusPollTimer = ref(null)
  const statusPollInFlight = ref(false)
  const activeSessionSelectionEnabled = ref(false)
  const activeSessions = ref({})

  const loadActiveSessions = () => {
    try {
      activeSessions.value = JSON.parse(localStorage.getItem('activeSessions') || '{}')
    } catch (e) {
      activeSessions.value = {}
    }
    ensureStatusPolling()
  }

  const activeSessionItems = computed(() =>
    Object.entries(activeSessions.value || {})
      .filter(([, meta]) => !!meta && !!meta.include_in_sidebar)
      .sort(([, a], [, b]) => (b?.lastUpdate || 0) - (a?.lastUpdate || 0))
      .map(([sessionId, meta]) => ({
        id: sessionId,
        sessionId,
        sessionStatus: meta?.status === 'completed' ? 'completed' : 'running',
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

  const startStatusPolling = () => {
    if (statusPollTimer.value) return
    statusPollTimer.value = setInterval(syncActiveSessionStatuses, 3000)
  }

  const stopStatusPolling = () => {
    if (!statusPollTimer.value) return
    clearInterval(statusPollTimer.value)
    statusPollTimer.value = null
  }

  const ensureStatusPolling = () => {
    const hasRunningSessions = Object.values(activeSessions.value || {}).some(s => s.status === 'running')
    if (activeSessionSelectionEnabled.value || hasRunningSessions) {
      syncActiveSessionStatuses()
      startStatusPolling()
    } else {
      stopStatusPolling()
    }
  }

  const syncActiveSessionStatuses = async () => {
    if (activeSessionItems.value.length === 0) return
    if (statusPollInFlight.value) return
    statusPollInFlight.value = true
    try {
      const serverSessions = await chatAPI.getActiveSessions(1200)
      const runningIds = new Set(
        (serverSessions || [])
          .filter(item => item && !item.is_completed)
          .map(item => item.session_id)
      )
      let changed = false
      const next = { ...activeSessions.value }
      Object.entries(next).forEach(([sessionId, meta]) => {
        if (!meta) return
        const nextStatus = runningIds.has(sessionId) ? 'running' : 'completed'
        if (meta.status !== nextStatus) {
          next[sessionId] = {
            ...meta,
            status: nextStatus,
            lastUpdate: Date.now()
          }
          changed = true
        }
      })
      if (changed) {
        activeSessions.value = next
        persistActiveSessions()
      }
    } catch (error) {
      console.error('同步会话状态失败:', error)
    } finally {
      statusPollInFlight.value = false
    }
  }

  const isActiveSessionCurrent = (session) => {
    if (!activeSessionSelectionEnabled.value) return false
    return route.name === 'Chat' && route.query.session_id === session?.query?.session_id
  }

  const handleActiveSessionClick = (session) => {
    activeSessionSelectionEnabled.value = true
    ensureStatusPolling()
    onSessionClick(session)
    if (session.sessionStatus === 'completed') {
      removeActiveSession(session.sessionId)
    }
  }

  const disableActiveSessionSelection = () => {
    activeSessionSelectionEnabled.value = false
    ensureStatusPolling()
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      window.addEventListener('active-sessions-updated', loadActiveSessions)
      loadActiveSessions()
      ensureStatusPolling()
    }
  })

  onUnmounted(() => {
    if (typeof window !== 'undefined') {
      window.removeEventListener('active-sessions-updated', loadActiveSessions)
    }
    stopStatusPolling()
  })

  return {
    activeSessionItems,
    handleActiveSessionClick,
    isActiveSessionCurrent,
    disableActiveSessionSelection
  }
}
