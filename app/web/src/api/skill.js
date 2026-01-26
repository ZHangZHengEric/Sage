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
}