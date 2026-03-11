import { ref } from 'vue'
import { chatAPI } from '@/api/chat'

// Module-level singletons
let activeSessions = ref({})
let sessionStreamOffsets = ref({})
let sseSource = null
let subscriberCount = 0

const readActiveSessionsCache = () => {
  try {
    return JSON.parse(localStorage.getItem('activeSessions') || '{}')
  } catch (e) {
    return {}
  }
}

// Initialize activeSessions from local storage once
activeSessions.value = readActiveSessionsCache()

const deriveSessionTitle = (content = '') => {
  const normalized = String(content || '').trim()
  if (!normalized) return '进行中的会话'
  return normalized
}

const syncSessionOffsetsFromActiveSessions = () => {
  const nextOffsets = {}
  Object.entries(activeSessions.value || {}).forEach(([sid, meta]) => {
    const parsed = Number(meta?.last_index || 0)
    nextOffsets[sid] = Number.isFinite(parsed) ? parsed : 0
  })
  sessionStreamOffsets.value = nextOffsets
}

const updateLocalCacheFromRemote = (remoteSessions) => {
  const localCache = readActiveSessionsCache()
  const remoteIds = new Set()
  
  // 1. Update local cache with remote sessions
  remoteSessions.forEach(session => {
    remoteIds.add(session.session_id)
    const existing = localCache[session.session_id] || {}
    
    localCache[session.session_id] = {
      ...existing,
      lastUpdate: session.last_activity * 1000,
      title: deriveSessionTitle(session.query || existing.title),
      user_input: session.query || existing.user_input || '',
      status: 'running',
      include_in_sidebar: true,
      last_index: existing.last_index || 0
    }
  })

  // 2. Mark missing running sessions as completed
  Object.keys(localCache).forEach(sid => {
    const session = localCache[sid]
    if (session.status === 'running' && !remoteIds.has(sid)) {
      localCache[sid] = {
        ...session,
        status: 'completed',
        completedAt: Date.now()
      }
    }
  })
  
  localStorage.setItem('activeSessions', JSON.stringify(localCache))
  activeSessions.value = localCache
  syncSessionOffsetsFromActiveSessions()
  window.dispatchEvent(new Event('active-sessions-updated'))
}

const connectSSE = async () => {
  if (sseSource) return

  try {
    const source = await chatAPI.subscribeActiveSessions()
    
    if (subscriberCount <= 0) {
      source.close()
      return
    }

    if (sseSource) {
      source.close()
      return
    }

    sseSource = source
    
    sseSource.onmessage = (event) => {
      try {
        const remoteSessions = JSON.parse(event.data)
        if (Array.isArray(remoteSessions)) {
          updateLocalCacheFromRemote(remoteSessions)
        }
      } catch (e) {
        console.error('[ActiveSessionCache] Failed to parse SSE active sessions:', e, event.data)
      }
    }

    sseSource.onerror = (err) => {
      console.error('[ActiveSessionCache] SSE connection error:', err)
      if (sseSource) {
        sseSource.close()
        sseSource = null
      }
      if (subscriberCount > 0) {
         setTimeout(() => {
           if (subscriberCount > 0 && !sseSource) {
              connectSSE()
           }
         }, 5000)
      }
    }
  } catch (e) {
    console.error('[ActiveSessionCache] Failed to start SSE sync:', e)
    // 连接失败不减少 subscriberCount，而是尝试重连
    if (subscriberCount > 0) {
         setTimeout(() => {
           if (subscriberCount > 0 && !sseSource) {
              connectSSE()
           }
         }, 5000)
    }
  }
}

const startSSESync = async () => {
  if (typeof EventSource === 'undefined') {
    return
  }

  subscriberCount++
  
  if (sseSource) {
    return 
  }

  connectSSE()
}

const stopSSESync = () => {
  subscriberCount--
  
  if (subscriberCount <= 0) {
    subscriberCount = 0
    if (sseSource) {
      sseSource.close()
      sseSource = null
    }
  }
}

export const useChatActiveSessionCache = () => {
  const handleActiveSessionsUpdated = () => {
    activeSessions.value = readActiveSessionsCache()
    syncSessionOffsetsFromActiveSessions()
  }

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
    // Frontend no longer actively inserts data.
    // Relies on SSE for sync.
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

  return {
    activeSessions,
    handleActiveSessionsUpdated,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    removeSessionFromCache,
    deriveSessionTitle,
    startSSESync,
    stopSSESync
  }
}
