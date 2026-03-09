import { baseAPI } from './base.js'

export const imAPI = {
  /**
   * Get IM configuration
   * @returns {Promise<Object>} IM configuration
   */
  getConfig() {
    return baseAPI.get('/api/im/config')
  },

  /**
   * Save IM configuration
   * @param {Object} config - IM configuration
   * @returns {Promise<Object>}
   */
  saveConfig(config) {
    return baseAPI.post('/api/im/config', config)
  },

  /**
   * Get IM service status
   * @returns {Promise<Object>}
   */
  getServiceStatus() {
    return baseAPI.get('/api/im/service/status')
  },
}
