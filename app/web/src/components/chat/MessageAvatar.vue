<template>
  <div 
    class="message-avatar"
    :style="{ background: avatarContent.bgColor }"
    :title="avatarContent.label"
  >
    <span class="avatar-emoji">{{ avatarContent.emoji }}</span>
  </div>
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
  }
})

// 根据消息类型、角色和工具名称确定头像内容
const avatarContent = computed(() => {
  if (props.role === 'user') {
    return {
      emoji: '👤',
      bgColor: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      label: '用户'
    }
  }
  
  if (props.role === 'assistant') {
    // 根据工具名称显示不同的头像
    if (props.messageType === 'tool_call' || props.messageType === 'tool_execution') {
      return getToolAvatar(props.toolName)
    }
    return {
      emoji: '🤖',
      bgColor: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
      label: 'AI助手'
    }
  }
  
  if (props.messageType === 'error') {
    return {
      emoji: '⚠️',
      bgColor: 'linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%)',
      label: '错误'
    }
  }
  
  if (props.messageType === 'system') {
    return {
      emoji: '⚙️',
      bgColor: 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
      label: '系统'
    }
  }
  
  // 默认头像
  return {
    emoji: '💬',
    bgColor: 'linear-gradient(135deg, #d299c2 0%, #fef9d7 100%)',
    label: '消息'
  }
})

// 根据工具名称返回对应的头像
const getToolAvatar = (toolName) => {
  const toolAvatars = {
    'search_codebase': {
      emoji: '🔍',
      bgColor: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      label: '代码搜索'
    },
    'view_files': {
      emoji: '📄',
      bgColor: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
      label: '查看文件'
    },
    'update_file': {
      emoji: '✏️',
      bgColor: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
      label: '编辑文件'
    },
    'write_to_file': {
      emoji: '📝',
      bgColor: 'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
      label: '写入文件'
    },
    'run_command': {
      emoji: '⚡',
      bgColor: 'linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)',
      label: '执行命令'
    },
    'list_dir': {
      emoji: '📁',
      bgColor: 'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
      label: '目录列表'
    },
    'search_by_regex': {
      emoji: '🔎',
      bgColor: 'linear-gradient(135deg, #d299c2 0%, #fef9d7 100%)',
      label: '正则搜索'
    },
    'delete_file': {
      emoji: '🗑️',
      bgColor: 'linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%)',
      label: '删除文件'
    },
    'rename_file': {
      emoji: '🔄',
      bgColor: 'linear-gradient(135deg, #ffc107 0%, #ff9800 100%)',
      label: '重命名文件'
    },
    'web_search': {
      emoji: '🌐',
      bgColor: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      label: '网络搜索'
    },
    'playwright_navigate': {
      emoji: '🎭',
      bgColor: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      label: '浏览器导航'
    },
    'playwright_click': {
      emoji: '👆',
      bgColor: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
      label: '点击操作'
    },
    'playwright_screenshot': {
      emoji: '📸',
      bgColor: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
      label: '截图'
    }
  }
  
  return toolAvatars[toolName] || {
    emoji: '🔧',
    bgColor: 'linear-gradient(135deg, #ffc107 0%, #ff9800 100%)',
    label: toolName || '工具执行'
  }
}
</script>

<style scoped>
.message-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  transition: transform 0.2s ease;
}

.message-avatar:hover {
  transform: scale(1.05);
}

.avatar-emoji {
  font-size: 18px;
  line-height: 1;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .message-avatar {
    width: 36px;
    height: 36px;
  }
  
  .avatar-emoji {
    font-size: 16px;
  }
}
</style>