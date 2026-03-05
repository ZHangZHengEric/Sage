<template>
  <Avatar class="h-8 w-8 shadow-sm transition-transform hover:scale-105 bg-muted/50" :class="{ 'border': !avatarUrl }">
    <AvatarImage v-if="avatarUrl && role === 'assistant'" :src="avatarUrl" :alt="avatarContent.label" />
    <AvatarFallback 
      :class="[avatarContent.bgClass, role === 'user' ? 'text-primary-foreground' : 'text-white']"
      class="flex items-center justify-center"
      :title="avatarContent.label"
    >
      <component :is="avatarContent.icon" class="h-4 w-4" />
    </AvatarFallback>
  </Avatar>
</template>

<script setup>
import { computed } from 'vue'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { User, Bot,  Zap, Settings, AlertTriangle, MessageSquare } from 'lucide-vue-next'

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
  agentId: {
    type: String,
    default: ''
  }
})

const avatarUrl = computed(() => {
  if (props.role === 'assistant' && props.agentId) {
    return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(props.agentId)}`
  }
  return ''
})

// 根据消息类型、角色和工具名称确定头像内容
const avatarContent = computed(() => {
  console.log(props.messageType, props.role, props.toolName, props.agentId)
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
       return {
        icon: Zap,
        bgClass: 'bg-indigo-500',
        label: '工具'
      }
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

</script>
