import request from '../utils/request.js'

export const imAPI = {
  /**
   * Get IM configuration
   * @returns {Promise<Object>} IM configuration
   */
  getConfig() {
    return request.get('/api/im/config')
  },

  /**
   * Save IM configuration
   * @param {Object} config - IM configuration
   * @returns {Promise<Object>}
   */
  saveConfig(config) {
    return request.post('/api/im/config', config)
  },

  /**
   * Get IM service status
   * @returns {Promise<Object>}
   */
  getServiceStatus() {
    return request.get('/api/im/service/status')
  },
}
