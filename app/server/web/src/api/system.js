import request from '../utils/request.js'

export const systemAPI = {
  getSystemInfo: () => {
    return request.get('/api/system/info')
  },
  updateSettings: (settings) => {
    return request.post('/api/system/update_settings', settings)
  }
}

export default systemAPI
