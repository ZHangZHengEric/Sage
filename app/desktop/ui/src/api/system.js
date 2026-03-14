import { baseAPI } from './base.js'

export const systemAPI = {
  getSystemInfo: () => {
    return baseAPI.get('/api/system/info')
  },
  updateSettings: (settings) => {
    return baseAPI.post('/api/system/update_settings', settings)
  },
  /** 获取最近 N 天的 Agent 工具使用统计 */
  getAgentUsageStats: (days) => {
    return baseAPI.post('/api/system/agent/usage-stats', { days })
  }
}

export default systemAPI
