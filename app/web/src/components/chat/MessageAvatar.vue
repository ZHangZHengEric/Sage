<template>
  <Avatar class="h-10 w-10 shadow-sm transition-transform hover:scale-105">
    <AvatarFallback 
      :style="{ background: avatarContent.bgColor }"
      class="text-lg text-white"
      :title="avatarContent.label"
    >
      {{ avatarContent.emoji }}
    </AvatarFallback>
  </Avatar>
</template>

<script setup>
import { computed } from 'vue'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'

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
      label: '运行命令'
    }
  }
  
  return toolAvatars[toolName] || {
    emoji: '🔧',
    bgColor: 'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)',
    label: '工具'
  }
}
</script>