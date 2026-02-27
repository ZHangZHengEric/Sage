import { baseAPI } from './base.js'

export const taskAPI = {
  /**
   * 获取任务状态
   * @param {string} sessionId - 会话ID
   * @returns {Promise<Object>}
   */
  getTaskStatus: (sessionId) => {
    return baseAPI.post(`/api/sessions/${sessionId}/tasks_status`, {})
  },

  /**
   * 获取工作空间文件
   * @param {string} sessionId - 会话ID
   * @returns {Promise<Object>}
   */
  getWorkspaceFiles: (sessionId) => {
    return baseAPI.post(`/api/sessions/${sessionId}/file_workspace`, {})
  },

  /**
   * 下载文件
   * @param {string} filePath - 文件路径
   * @returns {Promise<Blob>}
   */
  downloadFile: async (sessionId, filePath) => {
    const apiPrefix = import.meta.env.VITE_BACKEND_API_PREFIX || '';
    const url = `${apiPrefix}/api/sessions/${sessionId}/file_workspace/download?file_path=${encodeURIComponent(filePath)}`
    
    // 准备请求头
    const headers = {
      'Accept': 'application/json',
    }
    
    // 添加认证Token
    if (typeof localStorage !== 'undefined') {
        const token = localStorage.getItem('access_token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
    }
    
    // 使用原生fetch处理blob响应
    const response = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: headers
    })
    
    if (!response.ok) {
      // 尝试解析错误信息
      try {
        const errorData = await response.json()
        throw new Error(errorData.detail || errorData.message || `下载文件失败: ${response.status}`)
      } catch (e) {
        throw new Error(`下载文件失败: ${response.status}`)
      }
    }
    

    return response.blob()
  }
}