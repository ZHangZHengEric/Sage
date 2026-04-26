import request from '../utils/request.js'

class TaskAPI {
  constructor() {
    this.request = request
  }
  getRecurringTasks(params) {
    return this.request.get('/tasks/recurring', params)
  }

  getOneTimeTasks(params) {
    return this.request.get('/tasks/one-time', params)
  }

  createRecurringTask(data) {
    return this.request.post('/tasks/recurring', data)
  }

  createOneTimeTask(data) {
    return this.request.post('/tasks/one-time', data)
  }

  updateOneTimeTask(id, data) {
    return this.request.put(`/tasks/one-time/${id}`, data)
  }

  deleteOneTimeTask(id) {
    return this.request.delete(`/tasks/one-time/${id}`)
  }

  updateRecurringTask(id, data) {
    return this.request.put(`/tasks/recurring/${id}`, data)
  }

  deleteRecurringTask(id) {
    return this.request.delete(`/tasks/recurring/${id}`)
  }

  toggleTaskStatus(id, enabled) {
    return this.request.post(`/tasks/recurring/${id}/toggle`, { enabled })
  }

  getTaskHistory(id, params) {
    return this.request.get(`/tasks/recurring/${id}/history`, params)
  }

  /**
   * 获取工作空间文件
   * @param {string} agentId - Agent ID
   * @returns {Promise<Object>}
   */
  getWorkspaceFiles(agentId) {
    return this.request.post(`/api/agent/${agentId}/file_workspace`, {})
  }

  /**
   * 获取工作空间文件的流式 URL（用于视频等大文件，直接供浏览器流式播放）
   * 桌面端后端无需认证，可直接使用绝对 URL
   * @param {string} agentId - Agent ID
   * @param {string} filePath - 文件路径
   * @returns {string}
   */
  getFileStreamUrl(agentId, filePath) {
    if (!agentId || !filePath) return ''
    if (filePath.startsWith('http://') || filePath.startsWith('https://')) return filePath
    let apiPrefix = this.request.baseURL || ''
    if (apiPrefix.endsWith('/')) apiPrefix = apiPrefix.slice(0, -1)
    return `${apiPrefix}/api/agent/${agentId}/file_workspace/download?file_path=${encodeURIComponent(filePath)}`
  }

  /**
   * 下载文件
   * @param {string} agentId - Agent ID
   * @param {string} filePath - 文件路径
   * @returns {Promise<Blob>}
   */
  async downloadFile(agentId, filePath) {
    // 如果是 http/https 链接，直接下载
    if (filePath && (filePath.startsWith('http://') || filePath.startsWith('https://'))) {
      const response = await fetch(filePath, {
        method: 'GET',
        mode: 'cors',
      })
      if (!response.ok) {
        throw new Error(`下载文件失败: ${response.status}`)
      }
      return response.blob()
    }

    let apiPrefix = this.request.baseURL;
    // remove trailing slash
    if (apiPrefix.endsWith('/')) {
      apiPrefix = apiPrefix.slice(0, -1);
    }
    const url = `${apiPrefix}/api/agent/${agentId}/file_workspace/download?file_path=${encodeURIComponent(filePath)}`

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

  /**
   * 删除文件
   * @param {string} agentId - Agent ID (optional)
   * @param {string} sessionId - Session ID (optional)
   * @param {string} filePath - 文件路径
   * @returns {Promise<Object>}
   */
  deleteWorkspaceFile(agentId, sessionId, filePath) {
    let url = ''
    if (agentId) {
      url = `/api/agent/${agentId}/file_workspace/delete?file_path=${encodeURIComponent(filePath)}`
    } else if (sessionId) {
      url = `/api/sessions/${sessionId}/file_workspace/delete?file_path=${encodeURIComponent(filePath)}`
    } else {
      throw new Error('agentId or sessionId is required')
    }
    return this.request.delete(url)
  }

  /**
   * 上传文件到工作空间
   * @param {string} agentId - Agent ID
   * @param {File} file - 文件对象
   * @param {string} targetPath - 目标路径（可选）
   * @returns {Promise<Object>}
   */
  uploadWorkspaceFile(agentId, file, targetPath = '') {
    const formData = new FormData()
    formData.append('file', file)
    if (targetPath) {
      formData.append('target_path', targetPath)
    }
    return this.request.post(`/api/agent/${agentId}/file_workspace/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  }

  /**
   * 上传文件夹到工作空间（桌面端使用）
   * @param {string} agentId - Agent ID
   * @param {Array} files - 文件列表 [{source_path, relative_path}]
   * @param {string} targetFolder - 目标文件夹
   * @returns {Promise<Object>}
   */
  uploadWorkspaceFolder(agentId, files, targetFolder = '') {
    return this.request.post(`/api/agent/${agentId}/file_workspace/upload_folder`, {
      files,
      target_folder: targetFolder
    })
  }
}

export const taskAPI = new TaskAPI()
