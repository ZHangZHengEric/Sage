/**
 * Tool相关API接口
 */

import { baseAPI } from '../base.js'

/**
 * 获取所有工具列表
 * @param {Object} params - 查询参数
 * @returns {Promise<Array>}
 */
export const getTools = async (params = {}) => {
  return await baseAPI.get('/api/tools')
}

/**
 * 根据ID获取工具详情
 * @param {string} toolId - 工具ID
 * @returns {Promise<Object>}
 */
export const getToolDetail = async (toolId) => {
  return await baseAPI.get(`/api/tools/${toolId}`)
}

/**
 * 获取工具分类
 * @returns {Promise<Array>}
 */
export const getToolCategories = async () => {
  return await baseAPI.get('/api/tools/categories')
}

/**
 * 搜索工具
 * @param {Object} searchParams - 搜索参数
 * @param {string} searchParams.keyword - 关键词
 * @param {string} searchParams.category - 分类
 * @returns {Promise<Array>}
 */
export const searchTools = async (searchParams) => {
  return await baseAPI.get('/api/tools/search', searchParams)
}

/**
 * 获取推荐工具
 * @param {Object} params - 参数
 * @returns {Promise<Array>}
 */
export const getRecommendedTools = async (params = {}) => {
  return await baseAPI.get('/api/tools/recommended', params)
}

/**
 * 获取 MCP 服务器列表
 * @returns {Promise<Object>}
 */
export const getMcpServers = async () => {
  return await baseAPI.get('/api/mcp/list')
}

/**
 * 切换 MCP 服务器状态
 * @param {string} serverName - 服务器名称
 * @returns {Promise<Object>}
 */
export const toggleMcpServer = async (serverName) => {
  return await baseAPI.put(`/api/mcp/${serverName}/toggle`)
}

/**
 * 删除 MCP 服务器
 * @param {string} serverName - 服务器名称
 * @returns {Promise<Object>}
 */
export const deleteMcpServer = async (serverName) => {
  return await baseAPI.delete(`/api/mcp/${serverName}`)
}

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
export const addMcpServer = async (payload) => {
  return await baseAPI.post('/api/mcp/add', payload)
}