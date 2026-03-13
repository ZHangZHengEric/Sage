import { baseAPI } from './base.js'

export const systemAPI = {
  getSystemInfo: () => {
    return baseAPI.get('/api/system/info')
  },
  updateSettings: (settings) => {
    return baseAPI.post('/api/system/update_settings', settings)
  },
  getAgentUsageStats: (params) => {
    return baseAPI.post('/api/system/agent/usage-stats', params)
  }
}

export default systemAPI
