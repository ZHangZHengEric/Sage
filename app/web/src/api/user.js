import { baseAPI } from './base.js'

// 用户API接口
export const userAPI = {
  login: async (usernameOrEmail, password) => {
    return await baseAPI.post('/api/user/login', {
      username_or_email: usernameOrEmail,
      password
    })
  },
  register: async (username, password, email = '', phonenum = '') => {
    return await baseAPI.post('/api/user/register', {
      username,
      password,
      email,
      phonenum
    })
  },
  checkLogin: async () => {
    return await baseAPI.get('/api/user/check_login')
  },
  getUserInfo: async () => {
    return await baseAPI.get('/api/user/check_login')
  },
  refreshToken: async () => {
    return await baseAPI.post('/api/user/refresh-token')
  },
  changePassword: async (oldPassword, newPassword) => {
    return await baseAPI.post('/api/user/change-password', {
      old_password: oldPassword,
      new_password: newPassword
    })
  },
  updateProfile: async (userData) => {
    return await baseAPI.put('/api/user/profile', userData)
  },
  getUserList: async (page, pageSize) => {
    // baseAPI.get(url, params) - params directly passed as second argument
    return await baseAPI.get('/api/user/list', { page, page_size: pageSize })
  },
  deleteUser: async (userId) => {
    return await baseAPI.post('/api/user/delete', { user_id: userId })
  },
  addUser: async (data) => {
    return await baseAPI.post('/api/user/add', data)
  },
  getUserOptions: async () => {
    return await baseAPI.get('/api/user/options')
  }
}

export default userAPI
