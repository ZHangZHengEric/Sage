import request from '@/utils/request'

export const imAPI = {
  /**
   * Get IM configuration
   * @returns {Promise<Object>} IM configuration including service status
   */
  getConfig() {
    return request({
      url: '/api/im/config',
      method: 'get',
    })
  },

  /**
   * Save IM configuration
   * Config includes provider settings and service.running flag
   * @param {Object} config - IM configuration
   * @returns {Promise<Object>}
   */
  saveConfig(config) {
    return request({
      url: '/api/im/config',
      method: 'post',
      data: config,
    })
  },

  /**
   * Get IM service status
   * @returns {Promise<Object>}
   */
  getServiceStatus() {
    return request({
      url: '/api/im/service/status',
      method: 'get',
    })
  },
}
