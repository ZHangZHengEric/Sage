import React from 'react';
import './MessageTypeLabel.css';

const MessageTypeLabel = ({ messageType, role, toolName, type }) => {
  // 根据消息类型、角色和工具名称确定标签文本
  const getLabelText = () => {
    // 如果有type字段，优先显示type内容
    if (type) {
      return type;
    }
    
    if (role === 'user') {
      return '用户';
    }
    
    if (role === 'assistant') {
      if (messageType === 'tool_call' || messageType === 'tool_execution') {
        return getToolLabel(toolName);
      }
      return messageType || 'AI助手';
    }
    
    if (messageType === 'error') {
      return '错误';
    }
    
    if (messageType === 'system') {
      return '系统';
    }
    
    // 默认显示messageType或消息
    return messageType || '消息';
  };
  
  // 根据工具名称返回对应的标签
  const getToolLabel = (toolName) => {
    const toolLabels = {
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
    };
    
    return toolLabels[toolName] || toolName || '工具执行';
  };
  
  const labelText = getLabelText();
  
  return (
    <span className={`message-type-label ${role} ${messageType || ''}`}>
      {labelText}
    </span>
  );
};

export default MessageTypeLabel;