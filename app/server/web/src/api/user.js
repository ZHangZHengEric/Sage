import request from '../utils/request.js'

// 用户API接口
export const userAPI = {
  login: async (username, password) => {
    return await request.post('/api/auth/login', {
      username,
      password
    })
  },
  register: async (username, password) => {
    return await request.post('/api/auth/register', {
      username,
      password
    })
  },
  checkLogin: async () => {
    return await request.get('/api/auth/session')
  },
  logout: async () => {
    return await request.post('/api/auth/logout', {})
  },
  getUserInfo: async () => {
    return await request.get('/api/auth/session')
  },
  refreshToken: async () => {
    return await request.post('/api/user/refresh-token')
  },
  changePassword: async (oldPassword, newPassword) => {
    return await request.post('/api/user/change-password', {
      old_password: oldPassword,
      new_password: newPassword
    })
  },
  updateProfile: async (userData) => {
    return await request.put('/api/user/profile', userData)
  },
  getUserList: async (page, pageSize) => {
    // request.get(url, params) - params directly passed as second argument
    return await request.get('/api/user/list', { page, page_size: pageSize })
  },
  deleteUser: async (userId) => {
    return await request.post('/api/user/delete', { user_id: userId })
  },
  addUser: async (data) => {
    return await request.post('/api/user/add', data)
  },
  getUserOptions: async () => {
    return await request.get('/api/user/options')
  },
  // User Config
  getUserConfig: async () => {
    return await request.get('/api/user/config')
  },
  updateUserConfig: async (config) => {
    return await request.post('/api/user/config', { config })
  }
}

export default userAPI
