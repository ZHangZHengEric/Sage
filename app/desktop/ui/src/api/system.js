import request from '../utils/request.js'

export const systemAPI = {
  getSystemInfo: () => {
    return request.get('/api/system/info')
  },
  updateSettings: (settings) => {
    return request.post('/api/system/update_settings', settings)
  },
  /** 获取最近 N 天的 Agent 工具使用统计 */
  getAgentUsageStats: (days) => {
    return request.post('/api/system/agent/usage-stats', { days })
  }
}

export default systemAPI
