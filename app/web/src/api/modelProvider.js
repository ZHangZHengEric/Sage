import { baseAPI } from './base.js'

export const modelProviderAPI = {
  /**
   * 获取模型提供商列表
   * @returns {Promise<Object>}
   */
  listModelProviders: async () => {
    return await baseAPI.get('/api/llm-provider/list')
  },

  /**
   * 创建模型提供商
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  createModelProvider: async (data) => {
    return await baseAPI.post('/api/llm-provider/create', data)
  },

  /**
   * 更新模型提供商
   * @param {string} id
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  updateModelProvider: async (id, data) => {
    return await baseAPI.put(`/api/llm-provider/update/${id}`, data)
  },

  /**
   * 删除模型提供商
   * @param {string} id
   * @returns {Promise<Object>}
   */
  deleteModelProvider: async (id) => {
    return await baseAPI.delete(`/api/llm-provider/delete/${id}`)
  }
}
