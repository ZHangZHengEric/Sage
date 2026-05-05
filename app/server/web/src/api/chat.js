/**
 * Chat 相关 API 接口
 */

import request from '../utils/request.js'

const resolveRequestLanguage = (language) => {
  const savedLanguage = language || (typeof localStorage !== 'undefined' ? localStorage.getItem('language') : null)
  if (['ptBR', 'pt', 'pt-BR'].includes(savedLanguage)) return 'pt'
  if (['enUS', 'en', 'en-US'].includes(savedLanguage)) return 'en'
  return 'zh'
}

export const chatAPI = {

  getConversationMessages: async (conversationId) => {
    return await request.get(`/api/conversations/${conversationId}/messages`)
  },

  getSharedConversationMessages: async (conversationId) => {
    return await request.get(`/api/share/conversations/${conversationId}/messages`)
  },

  deleteConversation: async (conversationId) => {
    return await request.delete(`/api/conversations/${conversationId}`)
  },

  editLastUserMessage: async (conversationId, payload) => {
    return await request.post(`/api/conversations/${conversationId}/edit-last-user-message`, payload)
  },

  rerunConversationStream: async (conversationId, payload = {}, abortController = null) => {
    return await request.postStream(`/api/conversations/${conversationId}/rerun-stream`, payload, {
      signal: abortController
    })
  },

  getConversationsPaginated: async (params = {}) => {
    const queryParams = new URLSearchParams()
    if (params.page) queryParams.append('page', params.page)
    if (params.page_size) queryParams.append('page_size', params.page_size)
    if (params.search) queryParams.append('search', params.search)
    if (params.agent_id) queryParams.append('agent_id', params.agent_id)
    if (params.sort_by) queryParams.append('sort_by', params.sort_by)

    const url = `/api/conversations${queryParams.toString() ? '?' + queryParams.toString() : ''}`
    return await request.get(url)
  },

  streamChat: async (messageData, abortController = null) => {
    return await request.postStream('/api/web-stream', messageData, {
      signal: abortController
    })
  },

  optimizeUserInput: async (payload, config = {}) => {
    return await request.post('/api/chat/optimize-input', {
      ...payload,
      language: resolveRequestLanguage(payload?.language)
    }, {
      timeout: 1000 * 60 * 30,
      ...config
    })
  },

  optimizeUserInputStream: async (payload, config = {}) => {
    return await request.postStream('/api/chat/optimize-input/stream', {
      ...payload,
      language: resolveRequestLanguage(payload?.language)
    }, {
      timeout: 1000 * 60 * 30,
      ...config
    })
  },

  interruptSession: async (sessionId, message = '用户请求中断') => {
    return await request.post(`/api/sessions/${sessionId}/interrupt`, {
      message
    })
  },

  getSessionGoal: async (sessionId) => {
    return await request.get(`/api/sessions/${sessionId}/goal`)
  },

  setSessionGoal: async (sessionId, payload) => {
    return await request.post(`/api/sessions/${sessionId}/goal`, payload)
  },

  clearSessionGoal: async (sessionId) => {
    return await request.delete(`/api/sessions/${sessionId}/goal`)
  },

  completeSessionGoal: async (sessionId) => {
    return await request.post(`/api/sessions/${sessionId}/goal/complete`, {})
  },

  resumeStream: async (sessionId, lastIndex = 0, abortController = null) => {
    return await request.getStream(`/api/stream/resume/${sessionId}?last_index=${lastIndex}`, {
      signal: abortController
    })
  },


  subscribeActiveSessions: async () => {
    const controller = new AbortController()
    
    // 使用 getStream 以便通过拦截器添加 Authorization 头
    // request.sse 使用 EventSource 不支持自定义 header
    const response = await request.getStream('/api/stream/active_sessions', {
      signal: controller.signal,
      headers: {
        'Accept': 'text/event-stream'
      }
    })

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    
    // 模拟 EventSource 接口
    const eventSource = {
      close: () => controller.abort(),
      onmessage: null,
      onerror: null,
      readyState: 1 // OPEN
    }

    // 异步读取流
    ;(async () => {
      let buffer = ''
      let currentData = ''
      
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            // 流结束视为错误（连接断开），触发重连
            if (eventSource.onerror) eventSource.onerror(new Error('Stream closed'))
            break
          }
          
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split(/\r?\n/)
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            if (line.trim() === '') {
              if (currentData.trim() && eventSource.onmessage) {
                eventSource.onmessage({ data: currentData.trim() })
              }
              currentData = ''
            } else if (line.startsWith('data: ')) {
              currentData += line.slice(6) + '\n'
            }
          }
        }
      } catch (error) {
        if (error.name === 'AbortError') return
        if (eventSource.onerror) eventSource.onerror(error)
      }
    })()

    return eventSource
  }
}
