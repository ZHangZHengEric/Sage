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
        <div class="bg-destructive/10 text-destructive border border-destructive/20 rounded-2xl rounded-tl-sm px-5 py-3.5 shadow-sm overflow-hidden break-words w-full">
          <div class="font-semibold mb-1 flex items-center gap-2">
            <span class="i-lucide-alert-circle w-4 h-4"></span>
            {{ t('error.title') }}
          </div>
          <div class="opacity-90 text-sm leading-relaxed">{{ message.show_content || message.content || t('error.unknown') }}</div>
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
        <div class="bg-primary/95 text-primary-foreground rounded-2xl rounded-tr-sm px-5 py-3.5 shadow-sm overflow-hidden break-words text-sm leading-relaxed tracking-wide">
          <ReactMarkdown
            :content="formatMessageContent(message.content)"
          />
        </div>
      </div>
    </div>

    <!-- 助手消息 -->
    <div v-else-if="message.role === 'assistant' && !hasToolCalls && message.show_content" class="flex flex-row items-start gap-3 px-4">
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
        <div class="bg-card text-card-foreground border border-border/40 rounded-2xl rounded-tl-sm px-5 py-3.5 shadow-sm overflow-hidden break-words w-full">
          <ReactMarkdown
            :content="formatMessageContent(message.show_content)"
            :components="markdownComponents"
          />
        </div>
      </div>
    </div>

    <!-- 工具调用按钮 -->
    <div v-else-if="hasToolCalls" class="flex flex-row items-start gap-3 px-4 mb-2">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.message_type" role="assistant" :toolName="getToolName(message)" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
         <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground">
            {{ getLabel({ role: 'assistant', type: message.type, messageType: message.message_type, toolName: getToolName(message) }) }}
         </div>
         <div class="bg-secondary/30 text-secondary-foreground border border-border/30 rounded-2xl rounded-tl-sm p-2 shadow-sm overflow-hidden break-words w-full sm:w-auto min-w-[260px]">
          <div class="flex flex-col gap-2">
            <div
              v-for="(toolCall, index) in message.tool_calls"
              :key="toolCall.id || index"
              class="relative flex items-center justify-between p-2 rounded-xl bg-background border border-border/50 hover:border-primary/30 hover:shadow-md transition-all cursor-pointer group"
              @click="handleToolClick(toolCall, getToolResult(toolCall))"
            >
              <!-- Status Indicator -->
              <div class="absolute left-0 top-3 bottom-3 w-1 rounded-r-full transition-colors"
                   :class="getToolResult(toolCall) ? 'bg-green-500/50' : 'bg-blue-500/50'"></div>

              <div class="flex items-center gap-3 flex-1 min-w-0 pl-3">
       
                <div class="flex flex-col min-w-0 gap-0.5">
                  <span class="font-medium text-sm truncate text-foreground/90 group-hover:text-primary transition-colors">{{ toolCall.function?.name || 'Unknown Tool' }}</span>
                  <span class="text-[10px] text-muted-foreground truncate font-mono opacity-80 flex items-center gap-1">
                     <span class="w-1.5 h-1.5 rounded-full" :class="getToolResult(toolCall) ? 'bg-green-500' : 'bg-blue-500 animate-pulse'"></span>
                     {{ getToolResult(toolCall) ? t('toolCall.completed') : t('toolCall.executing') }}
                  </span>
                </div>
              </div>
              
              <div class="flex items-center gap-2">
                 <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-full" @click.stop="handleToolClick(toolCall, getToolResult(toolCall))">
                    <ChevronRight class="h-4 w-4" />
                 </Button>
              </div>
            </div>
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
import ReactMarkdown from './ReactMarkdown.vue'
import ReactECharts from './ReactECharts.vue'
import SyntaxHighlighter from './SyntaxHighlighter.vue'
import TokenUsage from './TokenUsage.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronRight, Terminal, FileText, Search, Zap } from 'lucide-vue-next'
import { getMessageLabel } from '@/utils/messageLabels'

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
          h(ReactECharts, { 
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
  const date = new Date(timestamp)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const getToolIcon = (name) => {
  if (!name) return Zap
  if (name.includes('search')) return Search
  if (name.includes('file') || name.includes('read')) return FileText
  if (name.includes('command') || name.includes('terminal')) return Terminal
  return Zap
}

const handleToolClick = (toolCall, toolResult) => {
  emit('toolClick', toolCall, toolResult)
}

const handleDownloadFile = (filePath) => {
  emit('downloadFile', filePath)
}
</script>

