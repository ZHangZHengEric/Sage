/**
 * Agent相关API接口
 */

import request from '../utils/request.js'

/**
 * @typedef {Object} AbilityItem
 * @property {string} id - 能力项唯一 ID（kebab-case）
 * @property {string} title - 短标题（中文）
 * @property {string} description - 能力说明（中文）
 * @property {string} promptText - 可直接复制使用的提示语（中文）
 */

export const agentAPI = {
  /**
   * 获取所有Agent列表
   * @returns {Promise<Array>}
   */
  getAgents: async () => {
    return await request.get('/api/agent/list')
  },

  /**
   * 创建新的Agent
   * @param {Object} agentData - Agent数据
   * @returns {Promise<Object>}
   */
  createAgent: async (agentData) => {
    return await request.post('/api/agent/create', agentData)
  },

  /**
   * 更新Agent
   * @param {string} agentId - Agent ID
   * @param {Object} updates - 更新数据
   * @returns {Promise<Object>}
   */
  updateAgent: async (agentId, updates) => {
    return await request.put(`/api/agent/${agentId}`, updates)
  },

  /**
   * 删除Agent
   * @param {string} agentId - Agent ID
   * @returns {Promise<boolean>}
   */
  deleteAgent: async (agentId) => {
    return await request.delete(`/api/agent/${agentId}`)
  },

  /**
   * 智能生成Agent配置
   * @param {string} description - Agent描述
   * @param {Array} selectedTools - 选中的工具列表
   * @returns {Promise<Object>}
   */
  generateAgentConfig: async (description, selectedTools) => {
    return await request.post('/api/agent/auto-generate', {
      agent_description: description,
      available_tools: selectedTools
    })
  },

  /**
   * 系统调用Agent
   * @param {Object} input - 输入数据
   * @returns {Promise<Object>}
   */
  systemPromptOptimize: async (input) => {
    return await request.post(`/api/agent/system-prompt/optimize`, input)
  },

  /**
   * 获取默认系统提示词模板
   * @param {string} language - 语言代码 (默认 'zh')
   * @returns {Promise<Object>}
   */
  getDefaultSystemPrompt: async (language = 'zh') => {
    return await request.get('/api/agent/template/default_system_prompt', { params: { language } })
  },

  /**
   * 获取Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @returns {Promise<Array>}
   */
  getAgentAuth: async (agentId) => {
    return await request.get(`/api/agent/${agentId}/auth`)
  },

  /**
   * 更新Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @param {Array<string>} userIds - 用户ID列表
   * @returns {Promise<Object>}
   */
  updateAgentAuth: async (agentId, userIds) => {
    return await request.post(`/api/agent/${agentId}/auth`, { user_ids: userIds })
  },

  /**
   * 获取指定 Agent 的能力列表
   * @param {Object} params
   * @param {string} params.agentId - Agent ID
   * @param {string} [params.sessionId] - 会话 ID
   * @param {Object} [params.context] - 额外上下文
   * @param {string} [params.language] - 语言代码（'zh' | 'en'），默认取本地语言设置
   * @returns {Promise<AbilityItem[]>}
   */
  getAgentAbilities: async ({ agentId, sessionId, context = {}, language }) => {
    const savedLanguage = language || (typeof localStorage !== 'undefined' ? localStorage.getItem('language') : null)
    const normalizedLanguage = ['enUS', 'en', 'en-US'].includes(savedLanguage) ? 'en' : 'zh'
    const data = await request.post('/api/agent/abilities', {
      agent_id: agentId,
      session_id: sessionId,
      context,
      language: normalizedLanguage
    })
    // 后端标准响应的 data 部分应为 { items: AbilityItem[] }
    return data?.items || []
  }
}
