/**
 * Agent相关API接口
 */

import { baseAPI } from './base.js'

export const agentAPI = {
  /**
   * 获取所有Agent列表
   * @returns {Promise<Array>}
   */
  getAgents: async () => {
    return await baseAPI.get('/api/agent/list')
  },


  /**
   * 创建新的Agent
   * @param {Object} agentData - Agent数据
   * @returns {Promise<Object>}
   */
  createAgent: async (agentData) => {
    return await baseAPI.post('/api/agent/create', agentData)
  },

  /**
   * 更新Agent
   * @param {string} agentId - Agent ID
   * @param {Object} updates - 更新数据
   * @returns {Promise<Object>}
   */
  updateAgent: async (agentId, updates) => {
    return await baseAPI.put(`/api/agent/${agentId}`, updates)
  },

  /**
   * 删除Agent
   * @param {string} agentId - Agent ID
   * @returns {Promise<boolean>}
   */
  deleteAgent: async (agentId) => {
    return await baseAPI.delete(`/api/agent/${agentId}`)
  },

  /**
   * 智能生成Agent配置
   * @param {string} description - Agent描述
   * @param {Array} selectedTools - 选中的工具列表
   * @returns {Promise<Object>}
   */
  generateAgentConfig: async (description, selectedTools) => {
    return await baseAPI.post('/api/agent/auto-generate', {
      agent_description: description,
      available_tools: selectedTools
    })
  },
  /**
   * 系统调用Agent
   * @param {Object} input - 输入数据
   * @returns {Promise<Object>}
   */
  systemPromptOptimize: async (input) => {
    return await baseAPI.post(`/api/agent/system-prompt/optimize`, input)
  },

  /**
   * 获取默认系统提示词模板
   * @param {string} language - 语言代码 (默认 'zh')
   * @returns {Promise<Object>}
   */
  getDefaultSystemPrompt: async (language = 'zh') => {
    return await baseAPI.get('/api/agent/template/default_system_prompt', { params: { language } })
  },

  /**
   * 获取Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @returns {Promise<Array>}
   */
  getAgentAuth: async (agentId) => {
    return await baseAPI.get(`/api/agent/${agentId}/auth`)
  },

  /**
   * 更新Agent授权用户列表
   * @param {string} agentId - Agent ID
   * @param {Array<string>} userIds - 用户ID列表
   * @returns {Promise<Object>}
   */
  updateAgentAuth: async (agentId, userIds) => {
    return await baseAPI.post(`/api/agent/${agentId}/auth`, { user_ids: userIds })
  },

  /**
   * 获取工作空间文件
   * @param {string} agentId - 会话ID
   * @returns {Promise<Object>}
   */
  getWorkspaceFiles: (agentId) => {
    return baseAPI.post(`/api/agent/${agentId}/file_workspace`, {})
  },

  /**
   * 下载文件
   * @param {string} agentId - 会话ID
   * @param {string} filePath - 文件路径
   * @returns {Promise<Blob>}
   */
  downloadFile: async (agentId, filePath) => {
    const apiPrefix = import.meta.env.VITE_BACKEND_API_PREFIX || '';
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