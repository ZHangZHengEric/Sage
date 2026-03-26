import request from '../utils/request.js'

// 用户API接口
export const userAPI = {
  login: async (usernameOrEmail, password) => {
    return await request.post('/api/user/login', {
      username_or_email: usernameOrEmail,
      password
    })
  },
  register: async (username, password, email = '', phonenum = '') => {
    return await request.post('/api/user/register', {
      username,
      password,
      email,
      phonenum
    })
  },
  checkLogin: async () => {
    return await request.get('/api/user/check_login')
  },
  getAuthProviders: async () => {
    return await request.get('/api/user/auth-providers')
  },
  logout: async () => {
    return await request.post('/api/user/logout', {})
  },
  getUserInfo: async () => {
    return await request.get('/api/user/check_login')
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
