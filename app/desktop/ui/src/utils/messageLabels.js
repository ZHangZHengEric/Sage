/**
 * 消息类型标签工具库
 * 提供消息类型和工具名称的标签映射功能
 */

// 消息类型标签映射 - 基础映射（用于非i18n场景）
export const messageTypeLabels = new Map([
  // 角色标签
  ['user', '用户'],
  ['system', '系统'],
  // 消息类型标签
  ['normal', '普通消息'],
  ['task_analysis', '任务分析'],
  ['reasoning_content', '推理思考'],
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
  ['stage_summary', '阶段总结'],
  ['do_subtask', '子任务'],
  ['do_subtask_result', '执行结果'],
  ['finish_task_content', '任务完成'],
  ['rewrite', '重写'],
  ['query_suggest', '查询建议'],
  ['chunk_start', '数据块开始'],
  ['json_chunk', '数据块'],
  ['chunk_end', '数据块结束']
])

// 工具名称到 i18n key 的映射
export const toolLabelKeys = {
  // 文件系统工具
  'file_read': 'tools.fileRead',
  'file_write': 'tools.fileWrite',
  'file_update': 'tools.fileUpdate',
  'download_file_from_url': 'tools.downloadFileFromUrl',
  // 文件解析工具
  'extract_text_from_non_text_file': 'tools.extractTextFromNonTextFile',
  // 命令执行工具
  'execute_shell_command': 'tools.executeShellCommand',
  'execute_python_code': 'tools.executePythonCode',
  'execute_javascript_code': 'tools.executeJavascriptCode',
  // 网页抓取工具
  'fetch_webpages': 'tools.fetchWebpages',
  // 图片理解工具
  'analyze_image': 'tools.analyzeImage',
  // 任务清单工具
  'todo_write': 'tools.todoWrite',
  'todo_read': 'tools.todoRead',
  // 任务中断工具
  'ask_followup_question': 'tools.askFollowupQuestion',
  // 记忆工具
  'remember_user_memory': 'tools.rememberUserMemory',
  'recall_user_memory': 'tools.recallUserMemory',
  'recall_user_memory_by_type': 'tools.recallUserMemoryByType',
  'forget_user_memory': 'tools.forgetUserMemory',
  'search_memory': 'tools.searchMemory',
  // 技能工具
  'load_skill': 'tools.loadSkill',
  // 搜索工具
  'search_web_page': 'tools.searchWebPage',
  'search_image_from_web': 'tools.searchImageFromWeb',
  // Fibre Agent 工具
  'sys_spawn_agent': 'tools.sysSpawnAgent',
  'sys_delegate_task': 'tools.sysDelegateTask',
  // 任务调度工具
  'list_tasks': 'tools.listTasks',
  'add_task': 'tools.addTask',
  'delete_task': 'tools.deleteTask',
  'complete_task': 'tools.completeTask',
  'enable_task': 'tools.enableTask',
  'get_task_details': 'tools.getTaskDetails',
  'update_task': 'tools.updateTask',
  // IM服务工具
  'send_message_through_im': 'tools.sendMessageThroughIm',
  'send_file_through_im': 'tools.sendFileThroughIm',
  'send_image_through_im': 'tools.sendImageThroughIm',
  'memory_search': 'tools.searchMemory',
  // 已有工具
  'search_codebase': 'tools.searchCodebase',
  'view_files': 'tools.viewFiles',
  'write_to_file': 'tools.writeToFile',
  'run_command': 'tools.runCommand',
  'list_dir': 'tools.listDir',
  'search_by_regex': 'tools.searchByRegex',
  'delete_file': 'tools.deleteFile',
  'rename_file': 'tools.renameFile',
  'web_search': 'tools.webSearch',
  'playwright_navigate': 'tools.playwrightNavigate',
  'playwright_click': 'tools.playwrightClick',
  'playwright_screenshot': 'tools.playwrightScreenshot',
  'playwright_fill': 'tools.playwrightFill',
  'playwright_hover': 'tools.playwrightHover',
  'playwright_evaluate': 'tools.playwrightEvaluate',
  'sys_spawn_agent': 'tools.sysSpawnAgent',
  'sys_delegate_task': 'tools.sysDelegateTask',
  'sys_finish_task': 'tools.sysFinishTask',
  'compress_conversation_history': 'tools.compressConversationHistory',
  'generate_image': 'tools.generateImage',
  'fetch_webpage': 'tools.fetchWebpage',
  'web_fetcher': 'tools.webFetcher',
  'todo_write': 'tools.todoWrite',
  'questionnaire': 'tools.questionnaire'
}

// 工具名称标签映射 - 中文回退
export const toolLabels = {
  // 文件系统工具
  'file_read': '读取文件',
  'file_write': '写入文件',
  'file_update': '更新文件',
  'download_file_from_url': '下载文件',
  // 文件解析工具
  'extract_text_from_non_text_file': '提取文件文本',
  // 命令执行工具
  'execute_shell_command': '执行命令',
  'execute_python_code': '执行Python',
  'execute_javascript_code': '执行JS',
  // 网页抓取工具
  'fetch_webpages': '抓取网页',
  // 图片理解工具
  'analyze_image': '图片理解',
  // 任务清单工具
  'todo_write': '待办任务',
  'todo_read': '读取待办',
  // 任务中断工具
  'ask_followup_question': '追问问题',
  // 记忆工具
  'remember_user_memory': '记住记忆',
  'recall_user_memory': '回忆记忆',
  'recall_user_memory_by_type': '按类型回忆',
  'forget_user_memory': '遗忘记忆',
  'search_memory': '搜索记忆',
  // 技能工具
  'load_skill': '加载技能',
  // 搜索工具
  'search_web_page': '网页搜索',
  'search_image_from_web': '图片搜索',
  // Fibre Agent 工具
  'sys_spawn_agent': '创建智能体',
  'sys_delegate_task': '任务委派',
  // 任务调度工具
  'list_tasks': '列出任务',
  'add_task': '添加任务',
  'delete_task': '删除任务',
  'complete_task': '完成任务',
  'enable_task': '启用任务',
  'get_task_details': '获取任务详情',
  'update_task': '更新任务',
  // IM服务工具
  'send_message_through_im': '发送IM消息',
  'send_file_through_im': '发送文件',
  'send_image_through_im': '发送图片',
  'memory_search': '搜索记忆',
  // 已有工具
  'search_codebase': '代码搜索',
  'view_files': '查看文件',
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
  'playwright_evaluate': 'JS执行',
  'sys_spawn_agent': '创建智能体',
  'sys_delegate_task': '任务委派',
  'sys_finish_task': '任务完成',
  'compress_conversation_history': '压缩历史消息',
  'generate_image': '生成图片',
  'execute_python_code': '执行Python',
  'fetch_webpage': '抓取网页',
  'web_fetcher': '网页抓取',
  'todo_write': '待办任务',
  'questionnaire': '信息收集'
}

/**
 * 根据工具名称返回对应的标签（支持i18n）
 * @param {string} toolName - 工具名称
 * @param {Function} t - i18n翻译函数，可选
 * @returns {string} 工具标签
 */
export const getToolLabel = (toolName, t = null) => {
  if (!toolName) return t ? t('tools.default') : '工具执行'

  // 如果有i18n函数，优先使用
  if (t) {
    const key = toolLabelKeys[toolName]
    if (key) {
      const translated = t(key)
      // 如果翻译结果和key相同，说明没有翻译，使用回退
      if (translated !== key) {
        return translated
      }
    }
  }

  // 使用中文回退
  return toolLabels[toolName] || toolName
}

/**
 * 根据消息类型、角色和工具名称确定标签文本
 * @param {Object} params - 参数对象
 * @param {string} params.role - 角色
 * @param {string} params.type - 消息类型
 * @param {string} params.toolName - 工具名称
 * @param {Function} params.t - i18n翻译函数，可选
 * @returns {string} 标签文本
 */
export const getMessageLabel = ({ role, type, toolName, t = null }) => {
  // 根据角色优先处理
  if (role === 'user') {
    return t ? t('roles.user') : messageTypeLabels.get('user')
  }

  if (role === 'assistant') {
    // 如果有工具名称，优先显示工具名称
    if (toolName) {
      return getToolLabel(toolName, t)
    }
    if (type === 'tool_call' || type === 'tool_execution') {
      return getToolLabel(toolName, t)
    }
    const label = messageTypeLabels.get(type)
    if (label) return label
    return t ? t('roles.assistant') : 'AI助手'
  }

  // 根据消息类型处理
  if (messageTypeLabels.has(type)) {
    return messageTypeLabels.get(type)
  }

  // 返回原始类型或默认值
  return type || (t ? t('common.message') : '消息')
}
