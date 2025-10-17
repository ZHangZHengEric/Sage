/**
 * Chat相关API接口
 */

import { baseAPI } from '../base.js'

/**
 * 发送聊天消息
 * @param {Object} messageData - 消息数据
 * @returns {Promise<Object>}
 */
export const sendMessage = async (messageData) => {
  return await baseAPI.post('/api/chat/send', messageData)
}


/**
 * 获取聊天历史
 * @param {Object} params - 查询参数
 * @param {string} params.sessionId - 会话ID
 * @param {number} params.page - 页码
 * @param {number} params.limit - 每页数量
 * @returns {Promise<Object>}
 */
export const getChatHistory = async (params = {}) => {
  return await baseAPI.get('/api/chat/history', params)
}

/**
 * 清空聊天历史
 * @param {string} sessionId - 会话ID
 * @returns {Promise<boolean>}
 */
export const clearChatHistory = async (sessionId) => {
  return await baseAPI.post('/api/chat/clear', { sessionId })
}

/**
 * 获取会话列表
 * @param {Object} params - 查询参数
 * @returns {Promise<Array>}
 */
export const getSessions = async (params = {}) => {
  return await baseAPI.get('/api/chat/sessions', params)
}

/**
 * 创建新会话
 * @param {Object} sessionData - 会话数据
 * @returns {Promise<Object>}
 */
export const createSession = async (sessionData = {}) => {
  return await baseAPI.post('/api/sessions', sessionData)
}

/**
 * 删除会话
 * @param {string} sessionId - 会话ID
 * @returns {Promise<boolean>}
 */
export const deleteSession = async (sessionId) => {
  return await baseAPI.delete(`/api/chat/sessions/${sessionId}`)
}

/**
 * 获取对话消息
 * @param {string} conversationId - 对话ID
 * @returns {Promise<Object>}
 */
export const getConversationMessages = async (conversationId) => {
  return await baseAPI.get(`/api/conversations/${conversationId}/messages`)
}

/**
 * 保存对话
 * @param {Object} conversationData - 对话数据
 * @returns {Promise<Object>}
 */
export const saveConversation = async (conversationData) => {
  return await baseAPI.post('/api/conversations', conversationData)
}

/**
 * 删除对话
 * @param {string} conversationId - 对话ID
 * @returns {Promise<boolean>}
 */
export const deleteConversation = async (conversationId) => {
  return await baseAPI.delete(`/api/conversations/${conversationId}`)
}

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
export const getConversationsPaginated = async (params = {}) => {
  const queryParams = new URLSearchParams()
  if (params.page) queryParams.append('page', params.page)
  if (params.page_size) queryParams.append('page_size', params.page_size)
  if (params.user_id) queryParams.append('user_id', params.user_id)
  if (params.search) queryParams.append('search', params.search)
  if (params.agent_id) queryParams.append('agent_id', params.agent_id)
  if (params.sort_by) queryParams.append('sort_by', params.sort_by)
  
  const url = `/api/conversations${queryParams.toString() ? '?' + queryParams.toString() : ''}`
  return await baseAPI.get(url)
}
