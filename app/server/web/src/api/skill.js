/**
 * Skill相关API接口
 */

import request from '../utils/request.js'

export const skillAPI = {
  /**
   * 获取所有技能列表
   * @param {Object} params - 查询参数
   * @param {string} params.dimension - 可选，按维度过滤 (system, user, agent, all)
   * @param {string} params.agent_id - 可选，过滤特定Agent的技能
   * @returns {Promise<Array>}
   */
  getSkills: async (params = {}) => {
    return await request.get('/api/skills', params)
  },

  /**
   * 获取Agent可用的技能列表（带维度来源标签）
   * @param {string} agentId - Agent ID
   * @returns {Promise<Array>} - 技能列表，每个技能包含name, description, source_dimension
   */
  getAgentAvailableSkills: async (agentId) => {
    return await request.get('/api/skills/agent-available', { agent_id: agentId })
  },

  /**
   * 上传技能 (ZIP)
   * @param {File} file - ZIP文件
   * @param {boolean} isSystem - 是否为系统技能
   * @param {Object} extraParams - 额外参数 (is_agent, agent_id 等)
   * @returns {Promise<Object>}
   */
  uploadSkill: async (file, isSystem = false, extraParams = {}) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('is_system', isSystem)
    // 添加额外参数
    if (extraParams.is_agent) {
      formData.append('is_agent', extraParams.is_agent)
    }
    if (extraParams.agent_id) {
      formData.append('agent_id', extraParams.agent_id)
    }
    // request.post handles FormData automatically
    return await request.post('/api/skills/upload', formData)
  },

  /**
   * 从 URL 导入技能
   * @param {Object} data - 导入参数
   * @param {string} data.url - 技能 ZIP 下载链接
   * @param {boolean} data.is_system - 是否为系统技能
   * @returns {Promise<Object>}
   */
  importSkillFromUrl: async (data) => {
    return await request.post('/api/skills/import-url', data)
  },

  /**
   * 删除技能
   * @param {string} skillName - 技能名称
   * @param {string} agentId - 可选，Agent ID，如果提供则删除Agent工作空间下的skill
   * @returns {Promise<Object>}
   */
  deleteSkill: async (skillName, agentId = null) => {
    const params = { name: skillName }
    if (agentId) {
      params.agent_id = agentId
    }
    return await request.delete('/api/skills', { params })
  },

  /**
   * 获取技能内容
   * @param {string} skillName - 技能名称
   * @returns {Promise<Object>}
   */
  getSkillContent: async (skillName) => {
    return await request.get('/api/skills/content', { name: skillName })
  },

  /**
   * 更新技能内容
   * @param {string} skillName - 技能名称
   * @param {string} content - 技能内容
   * @returns {Promise<Object>}
   */
  updateSkillContent: async (skillName, content) => {
    return await request.put('/api/skills/content', { name: skillName, content: content })
  },

  /**
   * 同步技能到Agent工作空间
   * @param {string} skillName - 技能名称
   * @param {string} agentId - Agent ID
   * @returns {Promise<Object>}
   */
  syncSkillToAgent: async (skillName, agentId) => {
    const formData = new FormData()
    formData.append('skill_name', skillName)
    formData.append('agent_id', agentId)
    return await request.post('/api/skills/sync-to-agent', formData)
  },

  /**
   * 批量同步技能到所有用户Agent工作空间
   * @param {string} agentId - Agent ID
   * @param {Array<string>} skillNames - 当前Agent选择的技能列表
   * @returns {Promise<Object>}
   */
  syncSkillsToAgentWorkspaces: async (agentId, skillNames = []) => {
    return await request.post('/api/skills/sync-to-agent-workspaces', {
      agent_id: agentId,
      skill_names: skillNames
    })
  }
}
