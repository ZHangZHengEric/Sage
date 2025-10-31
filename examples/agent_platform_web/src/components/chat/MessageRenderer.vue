<template>
  <div v-if="shouldRenderMessage">
    <!-- 错误消息 -->
    <div v-if="isErrorMessage" class="message error">
      <div class="avatar-container">
        <MessageAvatar messageType="error" role="assistant" />
        <MessageTypeLabel messageType="error" role="assistant" class="message-label" />
      </div>
      <div class="error-bubble">
          <div class="error-title">{{ t('error.title') }}</div>
          <div class="error-message">{{ message.show_content || message.content || t('error.unknown') }}</div>
      </div>
    </div>

    <!-- 用户消息 -->
    <div v-else-if="message.role === 'user' && message.message_type !== 'guide'" class="message user">
      <div class="avatar-container">
        <MessageAvatar :messageType="message.type || message.message_type" role="user" />
        <MessageTypeLabel :messageType="message.message_type" role="user" :type="message.type" class="message-label" />
      </div>
      <div class="user-bubble">
       <ReactMarkdown
            :content="formatMessageContent(message.content)"
          />
      </div>
    </div>

    <!-- 助手消息 -->
    <div v-else-if="message.role === 'assistant' && !hasToolCalls && message.show_content" class="message assistant">
      <div class="avatar-container">
        <MessageAvatar :messageType="message.message_type" role="assistant" />
        <MessageTypeLabel :messageType="message.message_type" role="assistant" :type="message.type" class="message-label" />
      </div>
      <div class="assistant-bubble">
        <ReactMarkdown
            :content="formatMessageContent(message.show_content)"
            :components="markdownComponents"
          />
      </div>
    </div>

    <!-- 工具调用按钮 -->
    <div v-else-if="hasToolCalls" class="message-container">
      <div class="message tool-calls">
        <div class="avatar-container">
          <MessageAvatar :messageType="message.message_type" role="assistant" />
          <MessageTypeLabel :messageType="message.message_type" role="assistant" :type="message.type" class="message-label" />
        </div>
        <div class="tool-calls-bubble">
        <div
              v-for="(toolCall, index) in message.tool_calls"
              :key="toolCall.id || index"
              class="tool-call-item"
              @click="handleToolClick(toolCall, getToolResult(toolCall))"
            >
              <div class="tool-call-main">
                <span class="tool-name">{{ toolCall.function?.name || 'Unknown Tool' }}</span>
                <span class="tool-status" :class="{ 'completed': getToolResult(toolCall), 'executing': !getToolResult(toolCall) }">
                  {{ getToolResult(toolCall) ? t('toolCall.completed') : t('toolCall.executing') }}
                </span>
              </div>
              <button class="tool-detail-button" @click.stop="handleToolClick(toolCall, getToolResult(toolCall))">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M9 18L15 12L9 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
            </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed, h } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import MessageAvatar from './MessageAvatar.vue'
import MessageTypeLabel from './MessageTypeLabel.vue'
import ReactMarkdown from './ReactMarkdown.vue'
import ReactECharts from './ReactECharts.vue'
import SyntaxHighlighter from './SyntaxHighlighter.vue'

const props = defineProps({
  message: {
    type: Object,
    required: true
  },
  messages: {
    type: Array,
    default: () => []
  },
  messageIndex: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['downloadFile', 'toolClick'])

const { t } = useLanguage()

// 计算属性
const shouldRenderMessage = computed(() => {
  return props.message.role !== 'tool'
})

const isErrorMessage = computed(() => {
  return props.message.type === 'error' || props.message.message_type === 'error'
})

const hasToolCalls = computed(() => {
  return props.message.tool_calls && Array.isArray(props.message.tool_calls) && props.message.tool_calls.length > 0
})


// Markdown组件配置
const markdownComponents = {
  code: ({ node, inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '')
    const language = match ? match[1] : ''
    
    // 处理 ECharts 代码块
    if (!inline && (language === 'echarts' || language === 'echart')) {
      try {
        const chartOption = JSON.parse(String(children).replace(/\n$/, ''))
        return h('div', { class: 'echarts-container', style: { margin: '10px 0' } }, [
          h(ReactECharts, { 
            option: chartOption, 
            style: { height: '400px', width: '100%' },
            opts: { renderer: 'canvas' }
          })
        ])
      } catch (error) {
        return h('div', { 
          class: 'echarts-error',
          style: { 
            padding: '10px', 
            backgroundColor: '#fee', 
            border: '1px solid #fcc',
            borderRadius: '4px',
            color: '#c33'
          }
        }, [
          h('strong', {}, 'ECharts 配置错误: '),
          error.message,
          h('pre', { style: { marginTop: '8px', fontSize: '12px' } }, String(children).replace(/\n$/, ''))
        ])
      }
    }
    
    // 普通代码块
    if (!inline && match) {
      return h(SyntaxHighlighter, {
        language: match[1],
        code: String(children).replace(/\n$/, ''),
        ...props
      })
    }
    
    // 行内代码
    return h('code', { class: className, ...props }, children)
  }
}

// 方法
const formatMessageContent = (content) => {
  if (!content) return ''
  
  // 处理特殊格式
  return content
    .replace(/\*\*(.*?)\*\*/g, '**$1**') // 保持粗体
    .replace(/\*(.*?)\*/g, '*$1*') // 保持斜体
    .replace(/`(.*?)`/g, '`$1`') // 保持行内代码
    .replace(/\n/g, '\n') // 保持换行
}

const getToolResult = (toolCall) => {
  if (!props.messages || !Array.isArray(props.messages)) return null
  
  // 在后续消息中查找对应的工具结果
  for (let i = props.messageIndex + 1; i < props.messages.length; i++) {
    const msg = props.messages[i]
    if (msg.role === 'tool' && msg.tool_call_id === toolCall.id) {
      return msg
    }
  }
  return null
}

const getFileName = (filePath) => {
  return filePath ? filePath.split('/').pop() : ''
}

const handleToolClick = (toolCall, toolResult) => {
  emit('toolClick', toolCall, toolResult)
}

const handleDownloadFile = (filePath) => {
  emit('downloadFile', filePath)
}
</script>

<style scoped>
.message {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
  padding: 0 16px;
  max-width: 100%;
  overflow: hidden;
}

/* 确保头像容器与消息气泡顶部对齐 */
.message .avatar-container {
  align-self: flex-start;
  margin-top: 0;
}

.message-container {
  margin-bottom: 16px;
}

/* 头像容器样式 */
.avatar-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  min-width: 48px;
  width: 48px;
}

/* 消息标签样式 */
.message-label {
  color: #333 !important;
  font-size: 11px !important;
  font-weight: 500 !important;
  text-align: center;
  white-space: normal !important;
  width: 48px !important; /* 固定宽度，约4个中文字符 */
  min-width: 48px !important;
  max-width: 48px !important;
  word-wrap: break-word;
  word-break: break-all;
  line-height: 1.2;
  background: none !important;
  border: none !important;
  padding: 0 !important;
  margin: 0 !important;
  overflow: visible;
}

/* 用户消息样式 */
.message.user {
  flex-direction: row-reverse;
}

.user-bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 18px 18px 4px 18px;
  padding: 12px 16px;
  max-width: 70%;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
  overflow: hidden;
  word-wrap: break-word;
  word-break: break-word;
  min-width: 0;
}

/* 助手消息样式 */
.message.assistant {
  flex-direction: row;
}

.assistant-bubble {
  background: white;
  border: 1px solid #e1e5e9;
  border-radius: 18px 18px 18px 18px;
  padding: 12px 16px;
  max-width: 70%;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  word-wrap: break-word;
  word-break: break-word;
  min-width: 0;
}

/* 错误消息样式 */
.message.error {
  flex-direction: row;
}

.error-bubble {
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
  color: white;
  border-radius: 18px 18px 18px 18px;
  padding: 12px 16px;
  max-width: 70%;
  box-shadow: 0 2px 8px rgba(255, 107, 107, 0.3);
  overflow: hidden;
  word-wrap: break-word;
  word-break: break-word;
  min-width: 0;
}

.error-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.error-message {
  opacity: 0.9;
}

/* 工具调用样式 */
.message.tool-calls {
  flex-direction: row;
}

.tool-calls-bubble {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: white;
  border-radius: 18px 18px 18px 18px;
  padding: 12px 16px;
  max-width: 70%;
  box-shadow: 0 2px 8px rgba(79, 172, 254, 0.3);
  overflow: hidden;
  word-wrap: break-word;
  word-break: break-word;
  min-width: 0;
}

.tool-calls-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-call-item {
  background: transparent;
  border: transparent;
  border-radius: 10px;
  padding: 10px 12px;
  color: white;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
}

.tool-call-item:hover {
  background:transparent;
}

.tool-call-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.tool-name {
  font-weight: 600;
  font-size: 14px;
  color: white;
}

.tool-status {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 12px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.tool-status.executing {
  background: rgba(255, 193, 7, 0.2);
  color: #ffc107;
  border: 1px solid rgba(255, 193, 7, 0.3);
  animation: pulse 1.5s infinite;
}

.tool-status.completed {
  background: rgba(40, 167, 69, 0.2);
  color: #28a745;
  border: 1px solid rgba(40, 167, 69, 0.3);
}

.tool-detail-button {
  background: transparent;
  border: transparent;
  border-radius: 8px;
  padding: 6px;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
}

.tool-detail-button:hover {
  background: transparent;
  transform: scale(1.05);
}

.tool-detail-button svg {
  transition: transform 0.2s ease;
}

.tool-call-item:hover .tool-detail-button svg {
  transform: translateX(2px);
}

/* 响应式设计 */
@media (max-width: 768px) {
  .tool-call-main {
    gap: 8px;
  }
  
  .tool-name {
    font-size: 13px;
  }
  
  .tool-status {
    font-size: 11px;
    padding: 2px 6px;
  }
  
  .tool-detail-button {
    min-width: 28px;
    height: 28px;
    padding: 4px;
  }
  
  .tool-detail-button svg {
    width: 14px;
    height: 14px;
  }
}

/* 增强的动画效果 */
@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(-10px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.tool-call-item {
  animation: slideIn 0.3s ease-out;
}

.tool-call-item:nth-child(2) {
  animation-delay: 0.1s;
}

.tool-call-item:nth-child(3) {
  animation-delay: 0.2s;
}

/* 工具执行样式 */
.message.tool-execution {
  flex-direction: row;
}

.tool-execution-bubble {
  background: white;
  border: 1px solid #e1e5e9;
  border-radius: 18px 18px 18px 18px;
  padding: 12px 16px;
  max-width: 70%;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.tool-name {
  font-weight: 600;
  color: #333;
}

.tool-status {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.tool-status.completed {
  background: #e8f5e8;
  color: #2d8f2d;
}

.tool-status.running {
  background: #fff3cd;
  color: #856404;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.tool-content {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.tool-file {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.download-button {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: white;
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s ease;
}

.download-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(79, 172, 254, 0.3);
}

/* 默认消息样式 */
.message-content {
  background: white;
  border: 1px solid #e1e5e9;
  border-radius: 12px;
  padding: 12px 16px;
  max-width: 70%;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* ECharts错误样式 */
.echarts-error {
  background: #fff2f0;
  border: 1px solid #ffccc7;
  border-radius: 6px;
  padding: 12px;
  color: #cf1322;
  font-size: 14px;
  text-align: center;
}

/* 响应式样式 - 小屏幕优化 */
@media (max-width: 768px) {
  .message {
    padding: 0 8px;
    gap: 8px;
  }
  
  .user-bubble,
  .assistant-bubble,
  .error-bubble,
  .tool-calls-bubble {
    max-width: 85%;
    padding: 10px 12px;
    font-size: 14px;
  }
  
  .message-content {
    max-width: 85%;
    padding: 10px 12px;
  }
}

@media (max-width: 480px) {
  .message {
    padding: 0 4px;
    gap: 6px;
  }
  
  .user-bubble,
  .assistant-bubble,
  .error-bubble,
  .tool-calls-bubble {
    max-width: 90%;
    padding: 8px 10px;
    font-size: 13px;
  }
  
  .message-content {
    max-width: 90%;
    padding: 8px 10px;
  }
}


</style>