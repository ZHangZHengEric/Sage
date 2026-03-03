import { BaseAPI } from './base.js'

class TaskAPI extends BaseAPI {
  getRecurringTasks(params) {
    return this.get('/tasks/recurring', params)
  }

  getOneTimeTasks(params) {
    return this.get('/tasks/one-time', params)
  }

  createRecurringTask(data) {
    return this.post('/tasks/recurring', data)
  }

  createOneTimeTask(data) {
    return this.post('/tasks/one-time', data)
  }

  updateOneTimeTask(id, data) {
    return this.put(`/tasks/one-time/${id}`, data)
  }

  deleteOneTimeTask(id) {
    return this.delete(`/tasks/one-time/${id}`)
  }

  updateRecurringTask(id, data) {
    return this.put(`/tasks/recurring/${id}`, data)
  }

  deleteRecurringTask(id) {
    return this.delete(`/tasks/recurring/${id}`)
  }

  toggleTaskStatus(id, enabled) {
    return this.post(`/tasks/recurring/${id}/toggle`, { enabled })
  }

  getTaskHistory(id, params) {
    return this.get(`/tasks/recurring/${id}/history`, params)
  }
  /**
   * 获取任务状态
   * @param {string} sessionId - 会话ID
   * @returns {Promise<Object>}
   */
  getTaskStatus(sessionId) {
    return this.post(`/api/sessions/${sessionId}/tasks_status`, {})
  }

  /**
   * 获取工作空间文件
   * @param {string} agentId - Agent ID
   * @returns {Promise<Object>}
   */
  getWorkspaceFiles(agentId) {
    return this.post(`/api/agent/${agentId}/file_workspace`, {})
  }

  /**
   * 下载文件
   * @param {string} agentId - Agent ID
   * @param {string} filePath - 文件路径
   * @returns {Promise<Blob>}
   */
  async downloadFile(agentId, filePath) {
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
}

export const taskAPI = new TaskAPI()
