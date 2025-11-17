/**
 * Chat相关API接口
 */

import { baseAPI } from './base.js'

export const chatAPI = {

  /**
   * 获取对话消息
   * @param {string} conversationId - 对话ID
   * @returns {Promise<Object>}
   */
  getConversationMessages: async (conversationId) => {
    return await baseAPI.get(`/api/conversations/${conversationId}/messages`)
  },

  /**
   * 删除对话
   * @param {string} conversationId - 对话ID
   * @returns {Promise<boolean>}
   */
  deleteConversation: async (conversationId) => {
    return await baseAPI.delete(`/api/conversations/${conversationId}`)
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
    return await baseAPI.get(url)
  },

  /**
   * 流式聊天
   * @param {Object} messageData - 消息数据
   * @param {AbortController} abortController - 中断控制器
   * @returns {Promise<Response>} 流式响应
   */
  streamChat: async (messageData, abortController = null) => {
    return await baseAPI.postStream('/api/stream', messageData, {
      signal: abortController
    })
  },

  /**
   * 中断会话
   * @param {string} sessionId - 会话ID
   * @param {string} message - 中断消息
   * @returns {Promise<Object>}
   */
  interruptSession: async (sessionId, message = '用户请求中断') => {
    return await baseAPI.post(`/api/sessions/${sessionId}/interrupt`, {
      message
    })
  }
}
