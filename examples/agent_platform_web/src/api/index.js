/**
 * API模块入口文件
 * 统一导出所有API接口
 */

// 导入各个模块的API
import * as agentAPI from './modules/agent'
import * as chatAPI from './modules/chat'
import * as toolAPI from './modules/tool'
import * as userAPI from './modules/user'
import * as taskAPI from './modules/task'

// 统一导出
export {
  agentAPI,
  chatAPI,
  toolAPI,
  userAPI,
  taskAPI
}

// 导出具体的API函数，方便直接使用
export const {
  // Agent相关
  getAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  generateAgentConfig,
  
  // Chat相关
  sendMessage,
  getChatHistory,
  clearChatHistory,
  getSessions,
  createSession,
  deleteSession,
  
  // Task相关
  getTaskStatus,
  getWorkspaceFiles,
  downloadFile
} = { ...agentAPI, ...chatAPI, ...taskAPI }

export const {
  getTools,
  getToolDetail
} = toolAPI

export const {
  getUserInfo,
  updateUserInfo
} = userAPI