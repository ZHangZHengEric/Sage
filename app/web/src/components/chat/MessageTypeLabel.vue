<template>
  <Badge :variant="badgeVariant" class="text-[10px] font-bold uppercase tracking-wider opacity-80">
    {{ labelText }}
  </Badge>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { getMessageLabel } from '@/utils/messageLabels'

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
  return getMessageLabel({
    role: props.role,
    type: props.type,
    toolName: props.toolName
  })
})

const badgeVariant = computed(() => {
  if (props.messageType === 'error') return 'destructive'
  return 'secondary'
})

</script>