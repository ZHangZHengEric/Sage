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
    
    // 检查内容类型，如果是HTML则抛出错误（可能是登录页或错误页）
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('text/html')) {
        // 尝试读取一小部分内容以提供更好的错误信息
        const text = await response.text();
        // 简单的检测是否是登录页
        if (text.includes('<html') || text.includes('<!DOCTYPE html')) {
             throw new Error('下载失败: 服务器返回了HTML页面，可能是因为未登录或会话过期。');
        }
        throw new Error('下载失败: 服务器返回了HTML内容而不是文件。');
    }

    return response.blob()
  }
}