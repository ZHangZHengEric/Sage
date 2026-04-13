import request from '../utils/request.js'

export const modelProviderAPI = {
  /**
   * 获取模型提供商列表
   * @returns {Promise<Object>}
   */
  listModelProviders: async () => {
    return await request.get('/api/llm-provider/list')
  },

  /**
   * 创建模型提供商
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  createModelProvider: async (data) => {
    return await request.post('/api/llm-provider/create', data)
  },

  /**
   * 更新模型提供商
   * @param {string} id
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  updateModelProvider: async (id, data) => {
    return await request.put(`/api/llm-provider/update/${id}`, data)
  },

  /**
   * 删除模型提供商
   * @param {string} id
   * @returns {Promise<Object>}
   */
  deleteModelProvider: async (id) => {
    return await request.delete(`/api/llm-provider/delete/${id}`)
  },

  /**
   * 验证模型提供商
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  verifyModelProvider: async (data) => {
    return await request.post('/api/llm-provider/verify-capabilities', data)
  },

  /**
   * 验证模型提供商是否支持多模态
   * @param {Object} data
   * @returns {Promise<Object>}
   */
  verifyMultimodal: async (data) => {
    return await request.post('/api/llm-provider/verify-multimodal', data)
  }
}
