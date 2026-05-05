import { ref } from 'vue'
import { chatAPI } from '@/api/chat'
import { sanitizeSessionTitle } from '@/utils/sessionTitle'
import { setDebugCounter, setDebugValue } from '@/utils/memoryDebug'

// Module-level singletons
let activeSessions = ref({})
let sessionStreamOffsets = ref({})
let sseSource = null
let subscriberCount = 0
let reconnectTimeoutId = null
let connectInFlight = false

const syncDebugCounters = () => {
  setDebugCounter('activeSession.sseSubscribers', subscriberCount)
  setDebugCounter('activeSession.hasReconnectTimer', reconnectTimeoutId ? 1 : 0)
  setDebugCounter('activeSession.connectInFlight', connectInFlight ? 1 : 0)
  setDebugCounter('activeSession.cachedSessions', Object.keys(activeSessions.value || {}).length)
  setDebugValue('activeSession.readyState', sseSource?.readyState ?? null)
}

const readActiveSessionsCache = () => {
  try {
    return JSON.parse(localStorage.getItem('activeSessions') || '{}')
  } catch (e) {
    return {}
  }
}

// Initialize activeSessions from local storage once
activeSessions.value = readActiveSessionsCache()
syncDebugCounters()

const deriveSessionTitle = (content = '') => {
  // 处理数组类型（messages 格式）
  if (Array.isArray(content)) {
    // 尝试从数组中提取文本内容
    const textParts = content
      .map(item => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          // 处理 OpenAI 格式的 message
          if (item.type === 'text' && item.text) return item.text
          if (item.content) return item.content
          if (item.text) return item.text
          if (item.message) return item.message
        }
        return ''
      })
      .filter(Boolean)
    content = textParts.join(' ')
  }
  // 处理对象类型（防止 [object Object]）
  else if (content && typeof content === 'object') {
    // 尝试提取对象中的文本字段
    content = content.text || content.content || content.message || JSON.stringify(content)
  }
  const normalized = sanitizeSessionTitle(String(content || '').trim())
  if (!normalized) return '进行中的会话'
  return normalized
}

const normalizeGoalPayload = (goal) => {
  if (!goal || typeof goal !== 'object') return null
  const objective = String(goal.objective || '').trim()
  if (!objective) return null
  return {
    objective,
    status: String(goal.status || '').trim() || 'active',
    created_at: goal.created_at || null,
    updated_at: goal.updated_at || null,
    completed_at: goal.completed_at || null,
    paused_reason: goal.paused_reason || null
  }
}

const normalizeGoalTransitionPayload = (transition) => {
  if (!transition || typeof transition !== 'object') return null
  const transitionType = String(transition.type || '').trim()
  if (!transitionType) return null
  return {
    type: transitionType,
    objective: transition.objective || null,
    status: transition.status || null,
    previous_objective: transition.previous_objective || null,
    previous_status: transition.previous_status || null
  }
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
    const remoteStatus = typeof session.status === 'string' ? session.status : 'running'
    const preserveStatus = ['interrupted', 'completed', 'error', 'interrupting'].includes(existing.status)
    const nextStatus = preserveStatus ? existing.status : remoteStatus
    
    // 确保 query 是字符串类型
    const queryText = deriveSessionTitle(session.query)
    localCache[session.session_id] = {
      ...existing,
      lastUpdate: session.last_activity * 1000,
      title: queryText,
      user_input: queryText,
      status: nextStatus,
      goal: normalizeGoalPayload(session.goal),
      goal_transition: normalizeGoalTransitionPayload(session.goal_transition),
      include_in_sidebar: true,
      last_index: existing.last_index || 0
    }
  })

  // 2. Mark missing running sessions as completed
  Object.keys(localCache).forEach(sid => {
    const session = localCache[sid]
    if ((session.status === 'running' || session.status === 'interrupting') && !remoteIds.has(sid)) {
      localCache[sid] = {
        ...session,
        status: session.status === 'interrupting' ? 'interrupted' : 'completed',
        completedAt: Date.now()
      }
    }
  })
  
  localStorage.setItem('activeSessions', JSON.stringify(localCache))
  activeSessions.value = localCache
  syncSessionOffsetsFromActiveSessions()
  window.dispatchEvent(new Event('active-sessions-updated'))
  syncDebugCounters()
}

const writeActiveSessionCache = (sessionId, patch = {}, persist = true) => {
  if (!sessionId) return
  const baseCache = {
    ...readActiveSessionsCache(),
    ...(activeSessions.value || {})
  }
  const existing = baseCache[sessionId] || activeSessions.value?.[sessionId] || {}
  const next = {
    ...existing,
    ...patch,
    session_id: sessionId,
    lastUpdate: Date.now()
  }

  baseCache[sessionId] = next
  activeSessions.value = baseCache
  syncSessionOffsetsFromActiveSessions()
  window.dispatchEvent(new Event('active-sessions-updated'))
  syncDebugCounters()

  if (persist) {
    localStorage.setItem('activeSessions', JSON.stringify(baseCache))
  }
}

const clearReconnectTimer = () => {
  if (reconnectTimeoutId !== null) {
    clearTimeout(reconnectTimeoutId)
    reconnectTimeoutId = null
  }
  syncDebugCounters()
}

const scheduleReconnect = () => {
  if (subscriberCount <= 0 || reconnectTimeoutId !== null || sseSource) return
  reconnectTimeoutId = setTimeout(() => {
    reconnectTimeoutId = null
    syncDebugCounters()
    if (subscriberCount > 0 && !sseSource) {
      connectSSE()
    }
  }, 5000)
  syncDebugCounters()
}

const connectSSE = async () => {
  if (sseSource || connectInFlight || subscriberCount <= 0) return
  connectInFlight = true
  syncDebugCounters()

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
    clearReconnectTimer()
    syncDebugCounters()
    
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
      const readyState = sseSource?.readyState
      if (readyState === EventSource.CLOSED && sseSource) {
        sseSource.close()
        sseSource = null
        scheduleReconnect()
      }
      syncDebugCounters()
    }
  } catch (e) {
    console.error('[ActiveSessionCache] Failed to start SSE sync:', e)
    scheduleReconnect()
  } finally {
    connectInFlight = false
    syncDebugCounters()
  }
}

const startSSESync = async () => {
  if (typeof EventSource === 'undefined') {
    return
  }

  subscriberCount++
  syncDebugCounters()
  
  if (sseSource) {
    return 
  }

  clearReconnectTimer()
  connectSSE()
}

const stopSSESync = () => {
  subscriberCount--
  syncDebugCounters()
  
  if (subscriberCount <= 0) {
    subscriberCount = 0
    clearReconnectTimer()
    if (sseSource) {
      sseSource.close()
      sseSource = null
    }
    syncDebugCounters()
  }
}

export const useChatActiveSessionCache = () => {
  const handleActiveSessionsUpdated = () => {
    activeSessions.value = readActiveSessionsCache()
    syncSessionOffsetsFromActiveSessions()
    syncDebugCounters()
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

  const updateActiveSession = (sessionId, isActive, title = null, userInput = null, persist = true, overrides = {}) => {
    if (!sessionId) return
    const existing = activeSessions.value?.[sessionId] || readActiveSessionsCache()[sessionId] || {}
    const nextStatus = typeof overrides.status === 'string'
      ? overrides.status
      : (isActive ? 'running' : 'completed')
    const next = {
      ...existing,
      ...overrides,
      title: title ?? existing.title ?? deriveSessionTitle(userInput || existing.user_input || ''),
      user_input: userInput ?? existing.user_input ?? title ?? '',
      status: nextStatus,
      include_in_sidebar: overrides.include_in_sidebar ?? true
    }
    writeActiveSessionCache(sessionId, next, persist)
  }

  const markSessionInterrupted = (sessionId, reason = '用户请求中断', persist = true) => {
    if (!sessionId) return
    updateActiveSession(sessionId, false, null, null, persist, {
      status: 'interrupted',
      interruptedAt: Date.now(),
      interruptReason: reason,
      include_in_sidebar: true
    })
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
    syncDebugCounters()
  }

  return {
    activeSessions,
    handleActiveSessionsUpdated,
    getSessionLastIndex,
    updateActiveSessionLastIndex,
    updateActiveSession,
    markSessionInterrupted,
    removeSessionFromCache,
    deriveSessionTitle,
    startSSESync,
    stopSSESync
  }
}
