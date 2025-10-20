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
   * 根据ID获取Agent详情
   * @param {string} agentId - Agent ID
   * @returns {Promise<Object>}
   */
  getAgentById: async (agentId) => {
    return await baseAPI.get(`/api/agent/${agentId}`)
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
   * @returns {Promise<Object>}
   */
  generateAgentConfig: async (description) => {
    return await baseAPI.post('/api/agent/auto-generate', {
      agent_description: description
    })
  }
}