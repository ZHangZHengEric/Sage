<template>
  <Avatar class="h-8 w-8 shadow-sm transition-transform hover:scale-105 border bg-muted/50">
    <AvatarFallback 
      :class="avatarContent.bgClass"
      class="flex items-center justify-center text-white"
      :title="avatarContent.label"
    >
      <component :is="avatarContent.icon" class="h-4 w-4" />
    </AvatarFallback>
  </Avatar>
</template>

<script setup>
import { computed } from 'vue'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { User, Bot, Terminal, FileText, Edit3, Save, Zap, Settings, AlertTriangle, MessageSquare, Search } from 'lucide-vue-next'

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
      icon: User,
      bgClass: 'bg-primary',
      label: '用户'
    }
  }
  
  if (props.role === 'assistant') {
    // 根据工具名称显示不同的头像
    if (props.messageType === 'tool_call' || props.messageType === 'tool_execution') {
      return getToolAvatar(props.toolName)
    }
    return {
      icon: Bot,
      bgClass: 'bg-blue-600',
      label: 'AI助手'
    }
  }
  
  if (props.messageType === 'error') {
    return {
      icon: AlertTriangle,
      bgClass: 'bg-destructive',
      label: '错误'
    }
  }
  
  if (props.messageType === 'system') {
    return {
      icon: Settings,
      bgClass: 'bg-muted-foreground',
      label: '系统'
    }
  }
  
  // 默认头像
  return {
    icon: MessageSquare,
    bgClass: 'bg-secondary-foreground',
    label: '消息'
  }
})

// 根据工具名称返回对应的头像
const getToolAvatar = (toolName) => {
  const toolAvatars = {
    'search_codebase': {
      icon: Search,
      bgClass: 'bg-violet-500',
      label: '代码搜索'
    },
    'view_files': {
      icon: FileText,
      bgClass: 'bg-cyan-500',
      label: '查看文件'
    },
    'update_file': {
      icon: Edit3,
      bgClass: 'bg-emerald-500',
      label: '编辑文件'
    },
    'file_update': {
      icon: Edit3,
      bgClass: 'bg-emerald-500',
      label: '编辑文件'
    },
    'write_to_file': {
      icon: Save,
      bgClass: 'bg-pink-500',
      label: '写入文件'
    },
    'run_command': {
      icon: Terminal,
      bgClass: 'bg-orange-500',
      label: '运行命令'
    }
  }
  
  return toolAvatars[toolName] || {
    icon: Zap,
    bgClass: 'bg-indigo-500',
    label: '工具'
  }
}
</script>