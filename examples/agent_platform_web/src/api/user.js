import request from '../utils/request.js'

// 用户API接口
export const userAPI = {
  login: (usernameOrEmail, password) => {
    return request.post('/api/user/login', {
      username_or_email: usernameOrEmail,
      password
    })
  },
  register: (username, password, email = '', phonenum = '') => {
    return request.post('/api/user/register', {
      username,
      password,
      email,
      phonenum
    })
  },
  checkLogin: () => {
    return request.get('/api/user/check_login')
  },
  getUserInfo: () => {
    return request.get('/api/user/check_login')
  },
  refreshToken: () => {
    return request.post('/api/user/refresh-token')
  },
  changePassword: (oldPassword, newPassword) => {
    return request.post('/api/user/change-password', {
      old_password: oldPassword,
      new_password: newPassword
    })
  },
  updateProfile: (userData) => {
    return request.put('/api/user/profile', userData)
  }
}

export default userAPI