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

const resolveRequestLanguage = (language) => {
  const savedLanguage = language || (typeof localStorage !== 'undefined' ? localStorage.getItem('language') : null)
  if (['ptBR', 'pt', 'pt-BR'].includes(savedLanguage)) return 'pt'
  if (['enUS', 'en', 'en-US'].includes(savedLanguage)) return 'en'
  return 'zh'
}

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

/**
 * @typedef {Object} AbilityItem
 * @property {string} id - 能力项唯一 ID（kebab-case）
 * @property {string} title - 短标题（中文）
 * @property {string} description - 能力说明（中文）
 * @property {string} promptText - 可直接复制使用的提示语（中文）
 */

export const agentAPI = {
  /**
   * 获取所有Agent列表
   * @returns {Promise<Array>}
   */
  getAgents: async () => {
    return await request.get('/api/agent/list')
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
   * 一键导入 OpenClaw 数据并创建 Agent
   * @returns {Promise<Object>}
   */
  importOpenclaw: async () => {
    return await request.post('/api/agent/import-openclaw', {})
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
      const normalizedLanguage = resolveRequestLanguage()
      const task = await request.post('/api/agent/auto-generate/submit', {
        agent_description: description,
        available_tools: selectedTools,
        language: normalizedLanguage
      }, {
        timeout: 1000 * 30,
        ...config
      })
      taskId = task.task_id

      const result = await pollAgentTask(taskId, {
        signal: config.signal,
        timeout: config.timeout ?? 1000 * 60 * 30,
        pollInterval: config.pollInterval
      })
      return { agent: result }
    } catch (error) {
      if (taskId && (config.signal?.aborted || error?.name === 'AbortError')) {
        try {
          await request.post(`/api/agent/tasks/${taskId}/cancel`, {})
        } catch (_) {}
      }
      throw error
    }
  },

  cancelAsyncTask: async (taskId, config = {}) => {
    return await request.post(`/api/agent/tasks/${taskId}/cancel`, {}, config)
  },
  /**
   * 系统调用Agent
   * @param {Object} input - 输入数据
   * @returns {Promise<Object>}
   */
  systemPromptOptimize: async (input, config = {}) => {
    let taskId = null
    try {
      const normalizedLanguage = resolveRequestLanguage()
      const task = await request.post(`/api/agent/system-prompt/optimize/submit`, {
        ...input,
        language: normalizedLanguage
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
   * 获取默认系统提示词模板
   * @param {string} language - 语言代码 (默认 'zh')
   * @returns {Promise<Object>}
   */
  getDefaultSystemPrompt: async (language = null) => {
    return await request.get('/api/agent/template/default_system_prompt', {
      params: { language: resolveRequestLanguage(language) }
    })
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
   * 获取指定 Agent 的能力列表
   * @param {Object} params
   * @param {string} params.agentId - Agent ID
   * @param {string} [params.sessionId] - 会话 ID
   * @param {Object} [params.context] - 额外上下文
   * @param {string} [params.language] - 语言代码（'zh' | 'en'），默认取本地语言设置
   * @returns {Promise<AbilityItem[]>}
   */
  getAgentAbilities: async ({ agentId, sessionId, context = {}, language }) => {
    const normalizedLanguage = resolveRequestLanguage(language)
    const data = await request.post('/api/agent/abilities', {
      agent_id: agentId,
      session_id: sessionId,
      context,
      language: normalizedLanguage
    })
    // 后端标准响应的 data 部分应为 { items: AbilityItem[] }
    return data?.items || []
  },

  /**
   * 设置指定 Agent 为默认 Agent
   * @param {string} agentId - Agent ID
   * @returns {Promise<Object>}
   */
  setDefaultAgent: async (agentId) => {
    return await request.post(`/api/agent/${agentId}/set-default`)
  }
}
