/**
 * Chat相关API接口
 */

import request from '../utils/request.js'

const resolveRequestLanguage = (language) => {
  const savedLanguage = language || (typeof localStorage !== 'undefined' ? localStorage.getItem('language') : null)
  if (['ptBR', 'pt', 'pt-BR'].includes(savedLanguage)) return 'pt'
  if (['enUS', 'en', 'en-US'].includes(savedLanguage)) return 'en'
  return 'zh'
}

export const chatAPI = {

  /**
   * 获取对话消息
   * @param {string} conversationId - 对话ID
   * @returns {Promise<Object>}
   */
  getConversationMessages: async (conversationId) => {
    return await request.get(`/api/conversations/${conversationId}/messages`)
  },

  /**
   * 获取分享的对话消息（无需登录）
   * @param {string} conversationId - 对话ID
   * @returns {Promise<Object>}
   */
  getSharedConversationMessages: async (conversationId) => {
    return await request.get(`/api/share/conversations/${conversationId}/messages`)
  },

  /**
   * 删除对话
   * @param {string} conversationId - 对话ID
   * @returns {Promise<boolean>}
   */
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

  /**
   * 分页获取对话列表
   * @param {Object} params - 查询参数
   * @param {number} params.page - 页码，从1开始
   * @param {number} params.page_size - 每页大小
   * @param {string} [params.user_id] - 用户ID（可选）
   * @param {string} [params.search] - 搜索关键词（可选）
   * @param {string} [params.agent_id] - Agent ID过滤（可选）
   * @param {string} [params.sort_by] - 排序方式（可选）
   * @returns {Promise<Object>} 分页对话列表响应
   */
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

  /**
   * 流式聊天
   * @param {Object} messageData - 消息数据
   * @param {AbortController} abortController - 中断控制器
   * @returns {Promise<Response>} 流式响应
   */
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

  /**
   * 中断会话
   * @param {string} sessionId - 会话ID
   * @param {string} message - 中断消息
   * @returns {Promise<Object>}
   */
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

  /**
   * 恢复流式聊天
   * @param {string} sessionId - 会话ID
   * @param {number} lastIndex - 已收到的消息索引
   * @param {AbortController} abortController - 中断控制器
   * @returns {Promise<Response>} 流式响应
   */
  resumeStream: async (sessionId, lastIndex = 0, abortController = null) => {
    return await request.getStream(`/api/stream/resume/${sessionId}?last_index=${lastIndex}`, {
      signal: abortController
    })
  },

  getActiveSessions: async (timeout = 800) => {
    // 兼容普通 GET
    return await request.get('/api/stream/active_sessions', {}, { timeout })
  },

  subscribeActiveSessions: async () => {
    return await request.sse('/api/stream/active_sessions')
  }
}
