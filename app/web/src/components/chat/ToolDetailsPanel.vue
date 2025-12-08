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
        <div class="section-header">
          <h4>{{ t('chat.toolParams') }}</h4>
          <el-button type="text" size="small"
            @click="copyToClipboard(formatJsonParams(toolExecution.function.arguments))" class="copy-btn">
            <el-icon>
              <DocumentCopy />
            </el-icon>
          </el-button>
        </div>
        <div class="json-card">
          <pre class="json-content">{{ formatJsonParams(toolExecution.function.arguments) }}</pre>
        </div>
      </div>
      <div class="tool-section">
        <div class="section-header">
          <h4>{{ t('chat.toolResult') }}</h4>
          <el-button type="text" size="small" @click="copyToClipboard(formatJsonParams(formatToolResult(toolResult)))"
            class="copy-btn">
            <el-icon>
              <DocumentCopy />
            </el-icon>
          </el-button>
        </div>
        <div class="json-card">
          <pre class="json-content">{{ formatJsonParams(formatToolResult(toolResult)) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useLanguage } from '@/utils/i18n.js'
import { ElMessage } from 'element-plus'
import { DocumentCopy } from '@element-plus/icons-vue'

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

// 复制到剪贴板
const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch (err) {
    console.error('复制失败:', err)
    ElMessage.error('复制失败')
  }
}

// 格式化工具结果
const formatToolResult = (result) => {
  if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result)
      return parsed.content || result
    } catch {
      return result
    }
  } else if (result && typeof result === 'object') {
    return result.content || JSON.stringify(result, null, 2)
  }
  return JSON.stringify(result, null, 2)
}

// 格式化JSON参数显示
const formatJsonParams = (params) => {
  if (typeof params === 'string') {
    try {
      const parsed = JSON.parse(params)
      return JSON.stringify(parsed, null, 2)
    } catch {
      return params
    }
  } else if (params && typeof params === 'object') {
    return JSON.stringify(params, null, 2)
  }
  return String(params)
}
</script>

<style scoped>
.tool-details-panel {
  width: 400px;
  border-left: 1px solid rgba(55, 53, 53, 0.1);
  background: transparent;
  display: flex;
  flex-direction: column;
}

.tool-details-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid rgba(55, 53, 53, 0.1);
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

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.tool-section h4 {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.7);
}

.copy-btn {
  padding: 4px 8px;
  color: rgba(0, 0, 0, 0.6);
  transition: color 0.2s;
}

.copy-btn:hover {
  color: #409eff;
}

.json-card {
  background: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.json-content {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 1rem;
  margin: 0;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
  color: #2c3e50;
}

.tool-code {
  background: rgba(187, 181, 181, 0.1);
  border: 1px solid rgba(97, 90, 90, 0.377);
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