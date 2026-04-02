/**
 * Agent相关API接口
 */

import request from '../utils/request.js'

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const timeoutId = setTimeout(() => {
    if (signal) {
      signal.removeEventListener('abort', onAbort)
    }
    resolve()
  }, ms)

  const onAbort = () => {
    clearTimeout(timeoutId)
    reject(new DOMException('Aborted', 'AbortError'))
  }

  if (signal) {
    if (signal.aborted) {
      onAbort()
      return
    }
    signal.addEventListener('abort', onAbort, { once: true })
  }
})

const pollAgentTask = async (taskId, config = {}) => {
  const pollInterval = config.pollInterval ?? 1200

  while (true) {
    const task = await request.get(`/api/agent/tasks/${taskId}`, {}, {
      signal: config.signal,
      timeout: config.timeout ?? 1000 * 60 * 30
    })

    if (task.status === 'completed') {
      return task.result
    }

    if (task.status === 'failed') {
      const error = new Error(task.error?.message || '任务执行失败')
      error.code = task.error?.code || 'TASK_FAILED'
      throw error
    }

    if (task.status === 'cancelled') {
      const error = new DOMException('Aborted', 'AbortError')
      error.code = 'TASK_CANCELLED'
      throw error
    }

    await sleep(pollInterval, config.signal)
  }
}

export const agentAPI = {
  /**
   * 获取所有Agent列表
   * @returns {Promise<Array>}
   */
  getAgents: async () => {
    return await request.get('/api/agent/list')
  },

  /**
   * 获取Agent详情
   * @param {string} agentId - Agent ID
   * @returns {Promise<Object>}
   */
  getAgentDetail: async (agentId) => {
    return await request.get(`/api/agent/${agentId}`)
  },


  /**
   * 创建新的Agent
   * @param {Object} agentData - Agent数据
   * @returns {Promise<Object>}
   */
  createAgent: async (agentData) => {
    return await request.post('/api/agent/create', agentData)
  },

  /**
   * 更新Agent
   * @param {string} agentId - Agent ID
   * @param {Object} updates - 更新数据
   * @returns {Promise<Object>}
   */
  updateAgent: async (agentId, updates) => {
    return await request.put(`/api/agent/${agentId}`, updates)
  },

  /**
   * 删除Agent
   * @param {string} agentId - Agent ID
   * @returns {Promise<boolean>}
   */
  deleteAgent: async (agentId) => {
    return await request.delete(`/api/agent/${agentId}`)
  },

  /**
   * 智能生成Agent配置
   * @param {string} description - Agent描述
   * @param {Array} selectedTools - 选中的工具列表
   * @returns {Promise<Object>}
   */
  generateAgentConfig: async (description, selectedTools, config = {}) => {
    let taskId = null
    try {
      const task = await request.post('/api/agent/auto-generate/submit', {
        agent_description: description,
        available_tools: selectedTools
      }, {
        timeout: 1000 * 30,
        ...config
      })
      taskId = task.task_id

      return await pollAgentTask(taskId, {
        signal: config.signal,
        timeout: config.timeout ?? 1000 * 60 * 30,
        pollInterval: config.pollInterval
      })
    } catch (error) {
      if (taskId && (config.signal?.aborted || error?.name === 'AbortError')) {
        try {
          await request.post(`/api/agent/tasks/${taskId}/cancel`, {})
        } catch (_) {}
      }
      throw error
    }
  },
  /**
   * 系统调用Agent
   * @param {Object} input - 输入数据
   * @returns {Promise<Object>}
   */
  systemPromptOptimize: async (input, config = {}) => {
    let taskId = null
    try {
      const task = await request.post(`/api/agent/system-prompt/optimize/submit`, input, {
        timeout: 1000 * 30,
        ...config
      })
      taskId = task.task_id

      return await pollAgentTask(taskId, {
        signal: config.signal,
        timeout: config.timeout ?? 1000 * 60 * 30,
        pollInterval: config.pollInterval
      })
    } catch (error) {
      if (taskId && (config.signal?.aborted || error?.name === 'AbortError')) {
        try {
          await request.post(`/api/agent/tasks/${taskId}/cancel`, {})
        } catch (_) {}
      }
      throw error
    }
  },

  /**
   * 获取默认系统提示词模板
   * @param {string} language - 语言代码 (默认 'zh')
   * @returns {Promise<Object>}
   */
  getDefaultSystemPrompt: async (language = 'zh') => {
    return await request.get('/api/agent/template/default_system_prompt', { params: { language } })
  },

  /**
   * 获取Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @returns {Promise<Array>}
   */
  getAgentAuth: async (agentId) => {
    return await request.get(`/api/agent/${agentId}/auth`)
  },

  /**
   * 更新Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @param {Array<string>} userIds - 用户ID列表
   * @returns {Promise<Object>}
   */
  updateAgentAuth: async (agentId, userIds) => {
    return await request.post(`/api/agent/${agentId}/auth`, { user_ids: userIds })
  },

  /**
   * 获取工作空间文件
   * @param {string} agentId - 会话ID
   * @param {string} sessionId - 会话ID (可选)
   * @returns {Promise<Object>}
   */
  getWorkspaceFiles: (agentId, sessionId) => {
    return request.post(`/api/agent/${agentId}/file_workspace`, {}, {
      params: { session_id: sessionId }
    })
  },

  /**
   * 下载文件
   * @param {string} agentId - 会话ID
   * @param {string} filePath - 文件路径
   * @param {string} sessionId - 会话ID (可选)
   * @returns {Promise<Blob>}
   */
  downloadFile: async (agentId, filePath, sessionId) => {
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

    const apiPrefix = import.meta.env.VITE_BACKEND_API_PREFIX || '';
    const params = new URLSearchParams({
      file_path: filePath
    })
    if (sessionId) {
      params.set('session_id', sessionId)
    }
    const url = `${apiPrefix}/api/agent/${agentId}/file_workspace/download?${params.toString()}`

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
