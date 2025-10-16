<template>
  <span :class="['message-type-label', role, messageType || '']">
    {{ labelText }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  messageType: {
    type: String,
    default: ''
  },
  role: {
    type: String,
    required: true
  },
  toolName: {
    type: String,
    default: ''
  },
  type: {
    type: String,
    default: ''
  }
})

// 根据消息类型、角色和工具名称确定标签文本
const labelText = computed(() => {
  // 如果有type字段，优先显示type内容
  if (props.type) {
    return props.type
  }
  
  if (props.role === 'user') {
    return '用户'
  }
  
  if (props.role === 'assistant') {
    if (props.messageType === 'tool_call' || props.messageType === 'tool_execution') {
      return getToolLabel(props.toolName)
    }
    return props.messageType || 'AI助手'
  }
  
  if (props.messageType === 'error') {
    return '错误'
  }
  
  if (props.messageType === 'system') {
    return '系统'
  }
  
  // 默认显示messageType或消息
  return props.messageType || '消息'
})

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
  }
  
  return toolLabels[toolName] || toolName || '工具执行'
}
</script>

<style scoped>
.message-type-label {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  border-radius: 4px;
  opacity: 0.8;
}

/* 用户标签样式 */
.message-type-label.user {
  background: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.9);
}

/* 助手标签样式 */
.message-type-label.assistant {
  background: #f0f2f5;
  color: #666;
}

/* 错误标签样式 */
.message-type-label.error {
  background: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.9);
}

/* 工具调用标签样式 */
.message-type-label.tool_call {
  background: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.9);
}

/* 工具执行标签样式 */
.message-type-label.tool_execution {
  background: #f0f2f5;
  color: #666;
}

/* 系统标签样式 */
.message-type-label.system {
  background: #f0f2f5;
  color: #666;
}
</style>