/**
 * Tool 相关 API 接口
 */

import request from '../utils/request.js'

export const toolAPI = {
  /**
   * 获取所有工具列表
   * @param {Object} params - 查询参数
   * @returns {Promise<Array>}
   */
  getTools: async (params = {}) => {
    return await request.get('/api/tools')
  },

  getBrowserExtensionStatus: async () => {
    return await request.get('/api/browser-extension/status')
  },

  /**
   * 主动探活浏览器扩展（入队 ping 命令，等待回包）
   * - 在线：~1s 内返回 online=true
   * - 掉线：等满 timeout 后强制标记为 offline 再返回
   */
  probeBrowserExtension: async (timeoutSec = 5) => {
    return await request.post(`/api/browser-extension/probe?timeout=${timeoutSec}`)
  },



  /**
   * 获取 MCP 服务器列表
   * @returns {Promise<Object>}
   */
  getMcpServers: async () => {
    return await request.get('/api/mcp/list')
  },

  /**
   * 切换 MCP 服务器状态
   * @param {string} serverName - 服务器名称
   * @returns {Promise<Object>}
   */
  toggleMcpServer: async (serverName) => {
    return await request.put(`/api/mcp/${serverName}/toggle`)
  },

  /**
   * 删除 MCP 服务器
   * @param {string} serverName - 服务器名称
   * @returns {Promise<Object>}
   */
  deleteMcpServer: async (serverName) => {
    return await request.delete(`/api/mcp/${serverName}`)
  },

  /**
   * 添加 MCP 服务器
   * @param {Object} mcpServerData - MCP 服务器数据
   * @param {string} mcpServerData.name - 服务器名称
   * @param {string} mcpServerData.protocol - 协议类型 (stdio|sse|streamable_http)
   * @param {string} mcpServerData.description - 描述
   * @param {string} [mcpServerData.command] - stdio 协议的命令
   * @param {Array<string>} [mcpServerData.args] - stdio 协议的参数
   * @param {Object<string, string>} [mcpServerData.env] - stdio 协议的环境变量
   * @param {string} [mcpServerData.sse_url] - SSE 协议的 URL
   * @param {string} [mcpServerData.streamable_http_url] - Streamable HTTP 协议的 URL
   * @returns {Promise<Object>}
   */
  addMcpServer: async (payload) => {
    return await request.post('/api/mcp/add', payload)
  },

  /**
   * 更新 MCP 服务器
   * @param {string} serverName - 服务器名称
   * @param {Object} payload - 服务器配置
   * @returns {Promise<Object>}
   */
  updateMcpServer: async (serverName, payload) => {
    return await request.put(`/api/mcp/${serverName}`, payload)
  },

  /**
   * 执行任意工具
   * @param {Object} payload - 执行请求
   * @returns {Promise<Object>}
   */
  execTool: async (payload) => {
    return await request.post('/api/tools/exec', payload)
  },

  /**
   * 刷新 MCP 服务器连接
   * @param {string} serverName - 服务器名称
   * @returns {Promise<Object>}
   */
  refreshMcpServer: async (serverName) => {
    return await request.post(`/api/mcp/${serverName}/refresh`)
  },

  /**
   * 预览 AnyTool 执行结果
   * @param {string} serverName - 服务器名称
   * @param {Object} payload - 预览请求
   * @returns {Promise<Object>}
   */
  previewMcpTool: async (serverName, payload) => {
    return await request.post(`/api/mcp/${serverName}/preview`, payload)
  },

  /**
   * 预览 AnyTool 草稿定义
   * @param {Object} payload - 草稿预览请求
   * @returns {Promise<Object>}
   */
  previewAnyToolDraft: async (payload) => {
    return await request.post('/api/mcp/anytool/preview-draft', payload)
  },

  /**
   * 新增或更新 AnyTool 中的单个工具
   * @param {Object} payload - 工具保存请求
   */
  upsertAnyToolTool: async (payload) => {
    return await request.post('/api/mcp/anytool/tool', payload)
  },

  /**
   * 删除 AnyTool 中的单个工具
   */
  deleteAnyToolTool: async (toolName, serverName = 'AnyTool') => {
    const encoded = encodeURIComponent(toolName)
    const params = serverName && serverName !== 'AnyTool' ? `?server_name=${encodeURIComponent(serverName)}` : ''
    return await request.delete(`/api/mcp/anytool/tool/${encoded}${params}`)
  }
}
