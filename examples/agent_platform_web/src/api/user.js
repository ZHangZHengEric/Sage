/**
 * User相关API接口
 */

import { baseAPI } from './base.js'

export const userAPI = {
  /**
   * 获取用户信息
   * @returns {Promise<Object>}
   */
  getUserInfo: async () => {
    return await baseAPI.get('/api/user/info')
  },

  /**
   * 更新用户信息
   * @param {Object} userData - 用户数据
   * @returns {Promise<Object>}
   */
  updateUserInfo: async (userData) => {
    return await baseAPI.put('/api/user/update', userData)
  },

  /**
   * 用户登录
   * @param {Object} credentials - 登录凭据
   * @param {string} credentials.username - 用户名
   * @param {string} credentials.password - 密码
   * @returns {Promise<Object>}
   */
  login: async (credentials) => {
    return await baseAPI.post('/api/auth/login', credentials)
  },

  /**
   * 用户登出
   * @returns {Promise<boolean>}
   */
  logout: async () => {
    return await baseAPI.post('/api/auth/logout')
  },

  /**
   * 刷新token
   * @returns {Promise<Object>}
   */
  refreshToken: async () => {
    return await baseAPI.post('/api/auth/refresh')
  },

  /**
   * 修改密码
   * @param {Object} passwordData - 密码数据
   * @param {string} passwordData.oldPassword - 旧密码
   * @param {string} passwordData.newPassword - 新密码
   * @returns {Promise<boolean>}
   */
  changePassword: async (passwordData) => {
    return await baseAPI.put('/api/user/password', passwordData)
  }
}