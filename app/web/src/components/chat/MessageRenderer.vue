<template>
  <div v-if="shouldRenderMessage" class="flex flex-col gap-4 mb-4">
    <!-- 错误消息 -->
    <div v-if="isErrorMessage" class="flex flex-row gap-3 px-4">
      <div class="flex flex-col items-center gap-1.5 min-w-[48px] w-12 self-start">
        <MessageAvatar messageType="error" role="assistant" />
        <MessageTypeLabel messageType="error" role="assistant" class="w-12 text-[11px] font-medium text-center text-foreground/70" />
      </div>
      <div class="bg-destructive text-destructive-foreground rounded-2xl rounded-tl-sm px-4 py-3 max-w-[70%] shadow-sm overflow-hidden break-words">
          <div class="font-semibold mb-1">{{ t('error.title') }}</div>
          <div class="opacity-90">{{ message.show_content || message.content || t('error.unknown') }}</div>
      </div>
    </div>

    <!-- Token 使用消息 -->
    <div v-else-if="isTokenUsageMessage && tokenUsageData" class="flex justify-center px-4">
      <TokenUsage :token-usage="tokenUsageData" />
    </div>

    <!-- 用户消息 -->
    <div v-else-if="message.role === 'user' && message.message_type !== 'guide'" class="flex flex-row-reverse gap-3 px-4">
      <div class="flex flex-col items-center gap-1.5 min-w-[48px] w-12 self-start">
        <MessageAvatar :messageType="message.type || message.message_type" role="user" />
        <MessageTypeLabel :messageType="message.message_type" role="user" :type="message.type" class="w-12 text-[11px] font-medium text-center text-foreground/70" />
      </div>
      <div class="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-3 max-w-[70%] shadow-md overflow-hidden break-words">
       <ReactMarkdown
            :content="formatMessageContent(message.content)"
          />
      </div>
    </div>

    <!-- 助手消息 -->
    <div v-else-if="message.role === 'assistant' && !hasToolCalls && message.show_content" class="flex flex-row gap-3 px-4">
      <div class="flex flex-col items-center gap-1.5 min-w-[48px] w-12 self-start">
        <MessageAvatar :messageType="message.message_type" role="assistant" />
        <MessageTypeLabel :messageType="message.message_type" role="assistant" :type="message.type" class="w-12 text-[11px] font-medium text-center text-foreground/70" />
      </div>
      <div class="bg-card text-card-foreground border rounded-2xl rounded-tl-sm px-4 py-3 max-w-[70%] shadow-sm overflow-hidden break-words">
        <ReactMarkdown
            :content="formatMessageContent(message.show_content)"
            :components="markdownComponents"
          />
      </div>
    </div>

    <!-- 工具调用按钮 -->
    <div v-else-if="hasToolCalls" class="flex flex-row gap-3 px-4 mb-4">
      <div class="flex flex-col items-center gap-1.5 min-w-[48px] w-12 self-start">
        <MessageAvatar :messageType="message.message_type" role="assistant" />
        <MessageTypeLabel :messageType="message.message_type" role="assistant" :type="message.type" class="w-12 text-[11px] font-medium text-center text-foreground/70" />
      </div>
      <div class="bg-secondary/50 text-secondary-foreground border rounded-2xl rounded-tl-sm p-3 max-w-[70%] shadow-sm overflow-hidden break-words w-full sm:w-auto">
        <div class="flex flex-col gap-2">
        <div
              v-for="(toolCall, index) in message.tool_calls"
              :key="toolCall.id || index"
              class="flex items-center justify-between p-3 rounded-lg bg-background/50 hover:bg-background/80 transition-colors cursor-pointer border border-transparent hover:border-border"
              @click="handleToolClick(toolCall, getToolResult(toolCall))"
            >
              <div class="flex items-center gap-3 flex-1 min-w-0">
                <span class="font-medium text-sm truncate">{{ toolCall.function?.name || 'Unknown Tool' }}</span>
                <Badge :variant="getToolResult(toolCall) ? 'default' : 'secondary'" class="text-[10px] h-5 px-2">
                  {{ getToolResult(toolCall) ? t('toolCall.completed') : t('toolCall.executing') }}
                </Badge>
              </div>
              <Button variant="ghost" size="icon" class="h-8 w-8 ml-2 shrink-0" @click.stop="handleToolClick(toolCall, getToolResult(toolCall))">
                <ChevronRight class="h-4 w-4" />
              </Button>
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
import TokenUsage from './TokenUsage.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronRight } from 'lucide-vue-next'

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
        return h('div', { class: 'echarts-container', style: { margin: '10px 0' } }, [
          h(ReactECharts, { 
            option: chartOption, 
            style: { height: '400px', width: '100%' },
            opts: { renderer: 'canvas' }
          })
        ])
      } catch (error) {
        return h('div', { 
          class: 'p-3 bg-destructive/10 border border-destructive/20 rounded-md text-destructive text-sm'
        }, [
          h('strong', { class: 'font-semibold' }, 'ECharts 配置错误: '),
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

