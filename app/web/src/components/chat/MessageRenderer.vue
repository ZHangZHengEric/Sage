<template>
  <div v-if="shouldRenderMessage" class="flex flex-col gap-6 mb-6">
    <!-- 错误消息 -->
    <div v-if="isErrorMessage" class="flex flex-row gap-4 px-4">
      <div class="flex-none">
        <MessageAvatar messageType="error" role="assistant" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
        <div class="mb-1.5 ml-1 text-xs font-medium text-muted-foreground">
          {{ getLabel({ role: 'assistant', type: 'error' }) }}
        </div>
        <div class="bg-destructive/5 text-destructive border border-destructive/10 rounded-[20px] rounded-tl-[4px] px-6 py-4 shadow-sm overflow-hidden break-words w-full">
          <div class="opacity-90 text-[15px] leading-7 font-medium">{{ message.content || t('error.unknown') }}</div>
        </div>
      </div>
    </div>

    <!-- Token 使用消息 -->
    <div v-else-if="isTokenUsageMessage && tokenUsageData" class="flex justify-center px-4 my-2">
      <TokenUsage :token-usage="tokenUsageData" />
    </div>

    <!-- 用户消息 -->
    <div v-else-if="message.role === 'user' && message.message_type !== 'guide'" class="flex flex-row-reverse items-start gap-3 px-4 group">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.type || message.message_type" role="user" />
      </div>
      <div class="flex flex-col items-end max-w-[85%] sm:max-w-[75%]">
        <div class="mb-1 mr-1 text-xs font-medium text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity select-none">
          {{ getLabel({ role: 'user', type: message.type, messageType: message.message_type }) }}
        </div>
        <div class="bg-secondary/80 text-secondary-foreground rounded-[20px] rounded-tr-[4px] px-6 py-4 shadow-sm overflow-hidden break-all text-[15px] leading-7 tracking-wide font-sans">
          <MarkdownRenderer
            :content="formatMessageContent(message.content)"
          />
        </div>
      </div>
    </div>
    
    <!-- 任务分析消息 -->
    <div
      v-else-if="message.role === 'assistant' && (message.type === 'task_analysis' || message.message_type === 'task_analysis')"       class="flex flex-row items-start gap-3 px-4">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.message_type" role="assistant" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground flex items-center gap-2">
          {{ getLabel({ role: 'assistant', type: message.type, messageType: message.message_type }) }}
          <span v-if="message.timestamp" class="text-[10px] opacity-60 font-normal">
            {{ formatTime(message.timestamp) }}
          </span>
        </div>
        <div class="w-full">
           <TaskAnalysisMessage 
             :content="message.content" 
             :isStreaming="isStreaming"
           />
        </div>
      </div>
    </div>

    <!-- 助手消息 -->
    <div v-else-if="message.role === 'assistant' && !hasToolCalls && message.content" class="flex flex-row items-start gap-3 px-4">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.message_type" role="assistant" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
        <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground flex items-center gap-2">
          {{ getLabel({ role: 'assistant', type: message.type, messageType: message.message_type }) }}
          <span v-if="message.timestamp" class="text-[10px] opacity-60 font-normal">
            {{ formatTime(message.timestamp) }}
          </span>
        </div>
        <div class="text-foreground/90 overflow-hidden break-words w-full text-[15px] leading-7 font-sans py-1">
          <MarkdownRenderer
            :content="formatMessageContent(message.content)"
            :components="markdownComponents"
          />
        </div>
      </div>
    </div>

    <!-- 工具渲染 -->
    <div v-else-if="hasToolCalls" class="flex flex-row items-start gap-3 px-4 mb-2">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.message_type" role="assistant" :toolName="getToolName(message)" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
         <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground">
            {{ getLabel({ role: 'assistant', type: message.type, messageType: message.message_type, toolName: '工具调用  ' + getToolName(message) }) }}
            <span v-if="message.timestamp" class="text-[10px] opacity-60 font-normal">
            {{ formatTime(message.timestamp) }}
          </span>
         </div>
         <div class="tool-calls-bubble w-full" :class="{ 'custom-tool-bubble': isCustomToolMessage }">
           <div v-for="(toolCall, index) in message.tool_calls" :key="toolCall.id || index">
             <!-- Global Error Card -->
             <ToolErrorCard v-if="checkIsToolError(getParsedToolResult(toolCall))" :toolResult="getParsedToolResult(toolCall)" />
             <!-- Dynamic Tool Component -->
             <component
               v-else
               :is="getToolComponent(toolCall.function?.name)"
               :toolCall="toolCall"
               :toolResult="getParsedToolResult(toolCall)"
               :isLatest="index === message.tool_calls.length - 1 && isLatestMessage"
               @sendMessage="handleSendMessage"
               @click="handleToolClick"
             />
           </div>
         </div>
      </div>
    </div>
    
    <!-- Tool Details Modal -->
    <ToolDetailsPanel 
        :open="showToolDetails" 
        @update:open="showToolDetails = $event"
        :tool-execution="selectedToolExecution"
        :tool-result="toolResult" 
    />

  </div>
</template>

<script setup>
import { computed, h, ref } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import MessageAvatar from './MessageAvatar.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import EChartsRenderer from './EChartsRenderer.vue'
import SyntaxHighlighter from './SyntaxHighlighter.vue'
import TokenUsage from './TokenUsage.vue'
import { Terminal, FileText, Search, Zap } from 'lucide-vue-next'
import { getMessageLabel } from '@/utils/messageLabels'
import ToolErrorCard from './tools/ToolErrorCard.vue'
import ToolDefaultCard from './tools/ToolDefaultCard.vue'
import ToolDetailsPanel from './tools/ToolDetailsPanel.vue'
import TaskAnalysisMessage from './TaskAnalysisMessage.vue'
// Custom Tools
const TOOL_COMPONENT_MAP = {

}

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
  },
  readonly: {
    type: Boolean,
    default: false
  },
  isLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['downloadFile', 'toolClick', 'sendMessage'])

const { t } = useLanguage()

// 计算属性
const shouldRenderMessage = computed(() => {
  return props.message.role !== 'tool'
})

// 统一的 isStreaming 状态判断
const isStreaming = computed(() => {
  return props.isLoading && props.messageIndex === props.messages.length - 1
})

const isErrorMessage = computed(() => {
  return props.message.type === 'error' || props.message.message_type === 'error'
})

const isTokenUsageMessage = computed(() => {
  return props.message.type === 'token_usage' || props.message.message_type === 'token_usage'
})

const tokenUsageData = computed(() => {
  return props.message?.metadata?.token_usage || null
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
        return h('div', { class: 'echarts-container', style: { margin: '16px 0' } }, [
          h(EChartsRenderer, { 
            option: chartOption, 
            style: { height: '400px', width: '100%' },
            opts: { renderer: 'canvas' }
          })
        ])
      } catch (error) {
        return h('div', { 
          class: 'p-4 bg-destructive/5 border border-destructive/20 rounded-lg text-destructive text-sm'
        }, [
          h('strong', { class: 'font-semibold block mb-1' }, 'ECharts 配置错误'),
          h('div', { class: 'opacity-90' }, error.message),
          h('pre', { class: 'mt-2 p-2 bg-black/5 rounded text-xs overflow-x-auto' }, String(children).replace(/\n$/, ''))
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

const getToolName = (message) => {
    if (message.tool_calls && message.tool_calls.length > 0) {
        return message.tool_calls[0].function?.name || ''
    }
    return ''
}

const getLabel = ({ role, type, messageType, toolName }) => {
  return getMessageLabel({
    role,
    type: messageType || type, // 优先使用 messageType
    toolName
  })
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  
  let dateVal = timestamp
  const num = Number(timestamp)
  
  // 如果是数字且看起来像秒级时间戳（小于100亿，对应年份2286年之前）
  // Python后端常返回秒级浮点数时间戳，如 1769963248.061118
  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }
  
  const date = new Date(dateVal)
  // 检查日期是否有效
  if (isNaN(date.getTime())) return ''
  
  const now = new Date()
  const isToday = date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear()

  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } else {
    return date.toLocaleString([], {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  }
}

const getToolIcon = (name) => {
  if (!name) return Zap
  if (name.includes('search')) return Search
  if (name.includes('file') || name.includes('read')) return FileText
  if (name.includes('command') || name.includes('terminal')) return Terminal
  return Zap
}

const showToolDetails = ref(false)
const selectedToolExecution = ref(null)
const toolResult = ref(null)

const handleToolClick = (toolCall, result) => {
  // Prevent custom tools from triggering the detail modal via native click events
  // ToolDefaultCard explicitly emits 'click' with (toolCall, toolResult)
  // Custom tools (without explicit emit) trigger native click with (MouseEvent)
  if (toolCall instanceof Event) {
    return
  }
  
  selectedToolExecution.value = toolCall
  toolResult.value = result
  showToolDetails.value = true
  
  emit('toolClick', toolCall, result)
}

const handleDownloadFile = (filePath) => {
  emit('downloadFile', filePath)
}

const handleSendMessage = (text) => {
  emit('sendMessage', text)
}

const getParsedToolResult = (toolCall) => {
  const result = getToolResult(toolCall)
  if (!result) return null

  // If content is string, try to parse it
  if (result.content && typeof result.content === 'string') {
    try {
      // Check if it looks like JSON
      if (result.content.trim().startsWith('{') || result.content.trim().startsWith('[')) {
          return {
            ...result,
            content: JSON.parse(result.content)
          }
      }
    } catch (e) {
      console.warn('Failed to parse tool result content:', e)
      return result
    }
  }
  return result
}

const checkIsToolError = (result) => {
    if (!result) return false
    if (result.is_error || result.status === 'error') return true
    if (result.content && typeof result.content === 'string' && result.content.toLowerCase().startsWith('error:')) return true
    return false
}

const isLatestMessage = computed(() => {
    // 如果readonly，所有消息都不是最新
    if (props.readonly) return false
    
    // If it's the last message, it's definitely latest
    if (props.messageIndex === props.messages.length - 1) return true
    
    // Check if there are any user messages after this one
    // If no user message follows, it is considered the latest turn
    for (let i = props.messageIndex + 1; i < props.messages.length; i++) {
        if (props.messages[i].role === 'user') {
            return false
        }
    }
    return true
})


const isCustomToolMessage = computed(() => {
    if (!hasToolCalls.value) return false
    return props.message.tool_calls.some(call => !!TOOL_COMPONENT_MAP[call.function?.name])
})

const getToolComponent = (toolName) => {
  if (!toolName) return ToolDefaultCard
  return TOOL_COMPONENT_MAP[toolName] || ToolDefaultCard
}

</script>


