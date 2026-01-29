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
    return await baseAPI.get('/api/skills')
  },

  /**
   * 上传技能 (ZIP)
   * @param {File} file - ZIP文件
   * @returns {Promise<Object>}
   */
  uploadSkill: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    // baseAPI.post handles FormData automatically
    return await baseAPI.post('/api/skills/upload', formData)
  },

  /**
   * 从 URL 导入技能
   * @param {string} url - 技能 ZIP 下载链接
   * @returns {Promise<Object>}
   */
  importSkillFromUrl: async (url) => {
    return await baseAPI.post('/api/skills/import-url', { url })
  }
}
