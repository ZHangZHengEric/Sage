/**
 * Tool相关API接口
 */

import { baseAPI } from './base.js'

export const toolAPI = {
  /**
   * 获取所有工具列表
   * @param {Object} params - 查询参数
   * @returns {Promise<Array>}
   */
  getTools: async (params = {}) => {
    return await baseAPI.get('/api/tools')
  },



  /**
   * 获取 MCP 服务器列表
   * @returns {Promise<Object>}
   */
  getMcpServers: async () => {
    return await baseAPI.get('/api/mcp/list')
  },

  /**
   * 切换 MCP 服务器状态
   * @param {string} serverName - 服务器名称
   * @returns {Promise<Object>}
   */
  toggleMcpServer: async (serverName) => {
    return await baseAPI.put(`/api/mcp/${serverName}/toggle`)
  },

  /**
   * 删除 MCP 服务器
   * @param {string} serverName - 服务器名称
   * @returns {Promise<Object>}
   */
  deleteMcpServer: async (serverName) => {
    return await baseAPI.delete(`/api/mcp/${serverName}`)
  },

  /**
   * 添加 MCP 服务器
   * @param {Object} mcpServerData - MCP 服务器数据
   * @param {string} mcpServerData.name - 服务器名称
   * @param {string} mcpServerData.protocol - 协议类型 (stdio|sse|streamable_http)
   * @param {string} mcpServerData.description - 描述
   * @param {string} [mcpServerData.command] - stdio 协议的命令
   * @param {Array<string>} [mcpServerData.args] - stdio 协议的参数
   * @param {string} [mcpServerData.sse_url] - SSE 协议的 URL
   * @param {string} [mcpServerData.streamable_http_url] - Streamable HTTP 协议的 URL
   * @returns {Promise<Object>}
   */
  addMcpServer: async (payload) => {
    return await baseAPI.post('/api/mcp/add', payload)
  },

  /**
   * 刷新 MCP 服务器连接
   * @param {string} serverName - 服务器名称
   * @returns {Promise<Object>}
   */
  refreshMcpServer: async (serverName) => {
    return await baseAPI.post(`/api/mcp/${serverName}/refresh`)
  }
}