/**
 * 消息类型标签工具库
 * 提供消息类型和工具名称的标签映射功能
 */

// 消息类型标签映射
export const messageTypeLabels = new Map([
  // 角色标签
  ['user', '用户'],
  ['system', '系统'],
  // 消息类型标签
  ['normal', '普通消息'],
  ['task_analysis', '任务分析'],
  ['task_decomposition', '任务拆解'],
  ['planning', '任务规划'],
  ['execution', '任务执行'],
  ['observation', '任务观察'],
  ['final_answer', '最终答案'],
  ['thinking', ' 思考'],
  ['tool_call', '工具调用'],
  ['tool_response', '工具响应'],
  ['tool_call_result', '工具结果'],
  ['tool_execution', '工具执行'],
  ['error', ' 错误'],
  ['guide', '指导'],
  ['handoff_agent', '智能体切换'],
  ['stage_summary', '任务阶段总结'],
  ['do_subtask', '子任务'],
  ['do_subtask_result', '任务执行结果'],
  ['rewrite', '重写'],
  ['query_suggest', '查询建议'],
  ['chunk', '数据块']
])

// 工具名称标签映射
export const toolLabels = {
  'search_codebase': '代码搜索',
  'view_files': '查看文件',
  'update_file': '编辑文件',
  'write_to_file': '写入文件',
  'run_command': '执行命令',
  'list_dir': '目录列表',
  'search_by_regex': '正则搜索',
  'delete_file': '删除文件',
  'rename_file': '重命名文件',
  'web_search': '网络搜索',
  'playwright_navigate': '浏览器导航',
  'playwright_click': '点击操作',
  'playwright_screenshot': '截图',
  'playwright_fill': '填写表单',
  'playwright_hover': '悬停操作',
  'playwright_evaluate': 'JS执行'
}

/**
 * 根据工具名称返回对应的标签
 * @param {string} toolName - 工具名称
 * @returns {string} 工具标签
 */
export const getToolLabel = (toolName) => {
  return toolLabels[toolName] || toolName || '工具执行'
}

/**
 * 根据消息类型、角色和工具名称确定标签文本
 * @param {Object} params - 参数对象
 * @param {string} params.role - 角色
 * @param {string} params.type - 消息类型
 * @param {string} params.toolName - 工具名称
 * @returns {string} 标签文本
 */
export const getMessageLabel = ({ role, type, toolName }) => {
  // 根据角色优先处理
  if (role === 'user') {
    return messageTypeLabels.get('user')
  }
  
  if (role === 'assistant') {
    if (type === 'tool_call' || type === 'tool_execution') {
      return getToolLabel(toolName)
    }
    return messageTypeLabels.get(type) || 'AI助手'
  }
  
  // 根据消息类型处理
  if (messageTypeLabels.has(type)) {
    return messageTypeLabels.get(type)
  }
  
  // 返回原始类型或默认值
  return type || '消息'
}