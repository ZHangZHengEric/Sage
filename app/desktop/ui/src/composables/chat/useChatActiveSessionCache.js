import { ref } from 'vue'

export const useChatActiveSessionCache = () => {
  const readActiveSessionsCache = () => {
    try {
      return JSON.parse(localStorage.getItem('activeSessions') || '{}')
    } catch (e) {
      return {}
    }
  }

  const activeSessions = ref(readActiveSessionsCache())
  const sessionStreamOffsets = ref({})

  const syncSessionOffsetsFromActiveSessions = () => {
    const nextOffsets = {}
    Object.entries(activeSessions.value || {}).forEach(([sid, meta]) => {
      const parsed = Number(meta?.last_index || 0)
      nextOffsets[sid] = Number.isFinite(parsed) ? parsed : 0
    })
    sessionStreamOffsets.value = nextOffsets
  }

  const handleActiveSessionsUpdated = () => {
    activeSessions.value = readActiveSessionsCache()
    syncSessionOffsetsFromActiveSessions()
  }

  syncSessionOffsetsFromActiveSessions()

  const getSessionLastIndex = (sessionId) => {
    const inMemory = Number(sessionStreamOffsets.value?.[sessionId] ?? 0)
    if (Number.isFinite(inMemory) && inMemory > 0) return inMemory
    const fromCache = Number(activeSessions.value?.[sessionId]?.last_index || 0)
    return Number.isFinite(fromCache) ? fromCache : 0
  }

  const updateActiveSessionLastIndex = (sessionId, lastIndex, persist = false) => {
    if (!sessionId || typeof lastIndex !== 'number') return
    const safeIndex = Number.isFinite(lastIndex) ? Math.max(0, Math.floor(lastIndex)) : 0
    sessionStreamOffsets.value = {
      ...sessionStreamOffsets.value,
      [sessionId]: safeIndex
    }

    // 更新内存中的状态
    if (activeSessions.value[sessionId]) {
      activeSessions.value[sessionId] = {
        ...activeSessions.value[sessionId],
        last_index: safeIndex
      }
    }

    if (!persist) return
    
    // 持久化到缓存，但不要覆盖 activeSessions.value（避免丢失内存中尚未持久化的新会话）
    const cache = readActiveSessionsCache()
    const existing = cache[sessionId]
    if (!existing) return
    
    cache[sessionId] = {
      ...existing,
      last_index: safeIndex,
      lastUpdate: Date.now()
    }
    localStorage.setItem('activeSessions', JSON.stringify(cache))
  }

  const updateActiveSession = (sessionId, isActive, title = null, userInput = null, persist = true) => {
    if (persist) {
      activeSessions.value = readActiveSessionsCache()
    }
 if (isActive) {
      const existing = activeSessions.value[sessionId] || {}
      const preservedTitle = existing.title && existing.title !== '进行中的会话' ? existing.title : null
      const preservedUserInput = existing.user_input || null
      activeSessions.value[sessionId] = {
        lastUpdate: Date.now(),
        title: preservedTitle || title || '进行中的会话',
        user_input: preservedUserInput || userInput || '',
        status: 'running',
        last_index: 0,
        include_in_sidebar: !!existing.include_in_sidebar
      }
    } else {
      const existing = activeSessions.value[sessionId]
      if (existing) {
        activeSessions.value[sessionId] = {
          ...existing,
          status: 'completed',
          completedAt: Date.now(),
          lastUpdate: Date.now()
        }
      }
    }
    syncSessionOffsetsFromActiveSessions()
    if (!persist) return
    localStorage.setItem('activeSessions', JSON.stringify(activeSessions.value))
    window.dispatchEvent(new Event('active-sessions-updated'))
  }

  const persistRunningSessionToCache = (sessionId, includeInSidebar = true) => {
    if (!sessionId) return
    const existing = activeSessions.value?.[sessionId]
    if (!existing) return
    if (existing.status !== 'running') return
    const cacheSnapshot = readActiveSessionsCache()
    cacheSnapshot[sessionId] = {
      ...existing,
      include_in_sidebar: includeInSidebar,
      last_index: Math.max(getSessionLastIndex(sessionId), Number(existing.last_index || 0)),
      lastUpdate: Date.now()
    }
    activeSessions.value = cacheSnapshot
    syncSessionOffsetsFromActiveSessions()
    localStorage.setItem('activeSessions', JSON.stringify(cacheSnapshot))
    window.dispatchEvent(new Event('active-sessions-updated'))
  }

  const removeSessionFromCache = (sessionId) => {
    if (!sessionId) return
    const cacheSnapshot = readActiveSessionsCache()
    if (!cacheSnapshot[sessionId]) return
    delete cacheSnapshot[sessionId]
    localStorage.setItem('activeSessions', JSON.stringify(cacheSnapshot))
    activeSessions.value = cacheSnapshot
    syncSessionOffsetsFromActiveSessions()
    window.dispatchEvent(new Event('active-sessions-updated'))
  }

  const deriveSessionTitle = (content = '') => {
    const normalized = String(content || '').trim()
    if (!normalized) return '进行中的会话'
    return normalized
  }

  return {
    activeSessions,
    handleActiveSessionsUpdated,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    persistRunningSessionToCache,
    removeSessionFromCache,
    deriveSessionTitle
  }
}
