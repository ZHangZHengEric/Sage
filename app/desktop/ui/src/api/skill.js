/**
 * Skill 相关 API 接口
 */

import request from '../utils/request.js'

export const skillAPI = {
  /**
   * 获取所有技能列表
   * @param {Object} params - 查询参数
   * @returns {Promise<Array>}
   */
  getSkills: async (params = {}) => {
    return await request.get('/api/skills')
  },

  /**
   * 上传技能 (ZIP)
   * @param {File} file - ZIP 文件
   * @returns {Promise<Object>}
   */
  uploadSkill: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    // request.post handles FormData automatically
    return await request.post('/api/skills/upload', formData)
  },

  /**
   * 从 URL 导入技能
   * @param {string} url - 技能 ZIP 下载链接
   * @returns {Promise<Object>}
   */
  importSkillFromUrl: async (data) => {
    return await request.post('/api/skills/import-url', data)
  },

  /**
   * 删除技能
   * @param {string} skillName - 技能名称
   * @returns {Promise<Object>}
   */
  deleteSkill: async (skillName) => {
    return await request.delete('/api/skills', { params: { name: skillName } })
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
  }
}
