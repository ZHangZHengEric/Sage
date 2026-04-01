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

const stripSessionControlTags = (text = '') => {
  let normalized = String(text || '')
  normalized = normalized.replace(/^\s*<enable_plan>\s*(true|false)\s*<\/enable_plan>\s*/i, '')
  normalized = normalized.replace(/^\s*<enable_deep_thinking>\s*(true|false)\s*<\/enable_deep_thinking>\s*/i, '')
  normalized = normalized.replace(/^<skill>.*?<\/skill>\s*/i, '')
  return normalized.trim()
}

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
  const normalized = stripSessionControlTags(String(content || '').trim())
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
    
    // 确保 query 是字符串类型
    const queryText = deriveSessionTitle(session.query)
    localCache[session.session_id] = {
      ...existing,
      lastUpdate: session.last_activity * 1000,
      title: queryText,
      user_input: queryText,
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
    stripSessionControlTags,
    startSSESync,
    stopSSESync
  }
}
