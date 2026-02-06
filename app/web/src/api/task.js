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
    const url = `/api/sessions/${sessionId}/file_workspace/download?file_path=${encodeURIComponent(filePath)}`
    
    // 使用原生fetch处理blob响应
    const response = await fetch(url, {
      method: 'GET',
      credentials: 'include'
    })
    
    if (!response.ok) {
      throw new Error(`下载文件失败: ${response.status}`)
    }
    
    return response.blob()
  }
}