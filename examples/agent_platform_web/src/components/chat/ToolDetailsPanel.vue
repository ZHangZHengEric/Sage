<template>
  <div class="tool-details-panel">
    <div class="tool-details-header">
      <h3>{{ t('chat.toolDetails') }}</h3>
      <el-button type="text" @click="$emit('close')">
        ×
      </el-button>
    </div>
    <div class="tool-details-content">
      <div class="tool-section">
        <h4>{{ t('chat.toolName') }}</h4>
        <p>{{ toolExecution.function.name }}</p>
      </div>
      <div class="tool-section">
        <h4>{{ t('chat.toolParams') }}</h4>
        <pre class="tool-code">{{ JSON.stringify(toolExecution.function.arguments, null, 2) }}</pre>
      </div>
      <div class="tool-section">
        <h4>{{ t('chat.toolResult') }}</h4>
        <pre class="tool-code">{{ formatToolResult(toolResult) }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useLanguage } from '@/utils/i18n.js'

// 使用国际化
const { t } = useLanguage()

// 定义 props
const props = defineProps({
  toolExecution: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [String, Object, Array],
    default: null
  }
})

// 定义 emits
const emit = defineEmits(['close'])

// 格式化工具结果
const formatToolResult = (result) => {
  if (typeof result === 'string') {
    return result
  }
  return JSON.stringify(result, null, 2)
}
</script>

<style scoped>
.tool-details-panel {
  width: 400px;
  border-left: 1px solid rgba(255, 255, 255, 0.1);
  background: #16213e;
  display: flex;
  flex-direction: column;
}

.tool-details-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.tool-details-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.tool-details-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.tool-section {
  margin-bottom: 1.5rem;
}

.tool-section h4 {
  margin: 0 0 0.5rem 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.7);
}

.tool-code {
  background: #0f1419;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  padding: 0.75rem;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.75rem;
  line-height: 1.4;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>