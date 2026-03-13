/**
 * Skill相关API接口
 */

import { baseAPI } from './base.js'

export const skillAPI = {
  /**
   * 获取所有技能列表
   * @param {Object} params - 查询参数
   * @returns {Promise<Array>}
   */
  getSkills: async (params = {}) => {
    return await baseAPI.get('/api/skills', params)
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
    // baseAPI.post handles FormData automatically
    return await baseAPI.post('/api/skills/upload', formData)
  },

  /**
   * 从 URL 导入技能
   * @param {Object} data - 导入参数
   * @param {string} data.url - 技能 ZIP 下载链接
   * @param {boolean} data.is_system - 是否为系统技能
   * @returns {Promise<Object>}
   */
  importSkillFromUrl: async (data) => {
    return await baseAPI.post('/api/skills/import-url', data)
  },

  /**
   * 删除技能
   * @param {string} skillName - 技能名称
   * @returns {Promise<Object>}
   */
  deleteSkill: async (skillName) => {
    return await baseAPI.delete('/api/skills', { params: { name: skillName } })
  },

  /**
   * 获取技能内容
   * @param {string} skillName - 技能名称
   * @returns {Promise<Object>}
   */
  getSkillContent: async (skillName) => {
    return await baseAPI.get('/api/skills/content', { name: skillName })
  },

  /**
   * 更新技能内容
   * @param {string} skillName - 技能名称
   * @param {string} content - 技能内容
   * @returns {Promise<Object>}
   */
  updateSkillContent: async (skillName, content) => {
    return await baseAPI.put('/api/skills/content', { name: skillName, content: content })
  }
}
