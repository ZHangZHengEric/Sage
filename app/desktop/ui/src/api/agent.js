/**
 * Agent相关API接口
 */

import { baseAPI } from './base.js'

export const agentAPI = {
  /**
   * 获取所有Agent列表
   * @returns {Promise<Array>}
   */
  getAgents: async () => {
    return await baseAPI.get('/api/agent/list')
  },


  /**
   * 创建新的Agent
   * @param {Object} agentData - Agent数据
   * @returns {Promise<Object>}
   */
  createAgent: async (agentData) => {
    return await baseAPI.post('/api/agent/create', agentData)
  },

  /**
   * 更新Agent
   * @param {string} agentId - Agent ID
   * @param {Object} updates - 更新数据
   * @returns {Promise<Object>}
   */
  updateAgent: async (agentId, updates) => {
    return await baseAPI.put(`/api/agent/${agentId}`, updates)
  },

  /**
   * 删除Agent
   * @param {string} agentId - Agent ID
   * @returns {Promise<boolean>}
   */
  deleteAgent: async (agentId) => {
    return await baseAPI.delete(`/api/agent/${agentId}`)
  },

  /**
   * 智能生成Agent配置
   * @param {string} description - Agent描述
   * @param {Array} selectedTools - 选中的工具列表
   * @returns {Promise<Object>}
   */
  generateAgentConfig: async (description, selectedTools) => {
    return await baseAPI.post('/api/agent/auto-generate', {
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
    return await baseAPI.post(`/api/agent/system-prompt/optimize`, input)
  },

  /**
   * 获取默认系统提示词模板
   * @param {string} language - 语言代码 (默认 'zh')
   * @returns {Promise<Object>}
   */
  getDefaultSystemPrompt: async (language = 'zh') => {
    return await baseAPI.get('/api/agent/template/default_system_prompt', { params: { language } })
  },

  /**
   * 获取Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @returns {Promise<Array>}
   */
  getAgentAuth: async (agentId) => {
    return await baseAPI.get(`/api/agent/${agentId}/auth`)
  },

  /**
   * 更新Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @param {Array<string>} userIds - 用户ID列表
   * @returns {Promise<Object>}
   */
  updateAgentAuth: async (agentId, userIds) => {
    return await baseAPI.post(`/api/agent/${agentId}/auth`, { user_ids: userIds })
  }
}