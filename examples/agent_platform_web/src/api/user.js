import request from '../utils/request.js'

// 用户API接口
export const userAPI = {
  // 用户登录
  login: (username, password) => {
    return request.post('/user/login', {
      username,
      password
    })
  },

  // 检查登录状态
  checkLogin: (username) => {
    return request.get(`/user/${username}`, {
      is_id: false
    })
  },
}

// 导出默认API
export default userAPI 