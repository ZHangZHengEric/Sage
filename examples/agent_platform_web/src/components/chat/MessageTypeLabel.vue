<template>
  <span :class="['message-type-label', role, messageType || '']">
    {{ labelText }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
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