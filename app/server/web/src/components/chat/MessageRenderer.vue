<template>
  <div v-if="shouldRenderMessage" class="flex flex-col gap-1 mb-1">
    <!-- 错误消息 -->
    <div v-if="isErrorMessage" class="flex flex-row gap-4 px-4">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar messageType="error" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none w-8" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
        <div class="mb-0.5 ml-1 text-xs font-medium text-muted-foreground">
          {{ getLabel({ role: 'assistant', type: 'error' }) }}
        </div>
        <div
          class="bg-destructive/5 text-destructive border border-destructive/10 rounded-[20px] rounded-tl-[4px] px-4 py-2.5 shadow-sm overflow-hidden break-words w-full">
          <div class="opacity-90 text-sm leading-6 font-medium">{{ message.content || t('error.unknown') }}</div>
        </div>
      </div>
    </div>

    <!-- Token 使用消息 -->
    <div v-else-if="isTokenUsageMessage && tokenUsageData" class="flex justify-center px-4 my-2">
      <TokenUsage :token-usage="tokenUsageData" />
    </div>

    <!-- 用户消息 -->
    <div v-else-if="message.role === 'user' && message.message_type !== 'guide'"
      class="flex flex-row-reverse items-start gap-3 px-4 group">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.type || message.message_type" role="user" />
      </div>
      <div class="flex flex-col items-end max-w-[85%] sm:max-w-[75%]">
        <div class="flex flex-col gap-1">
          <div v-if="getTextContent(message.content)" class="bg-secondary/80 text-secondary-foreground rounded-[20px] rounded-tr-[4px] px-4 py-2.5 shadow-sm overflow-hidden break-all text-sm leading-6 tracking-wide font-sans">
            <MarkdownRenderer
              :content="formatMessageContent(getTextContent(message.content))"
            />
          </div>
        <!-- 图片内容 -->
          <div v-if="getImageUrls(message.content).length > 0" class="flex flex-wrap gap-2">
            <div
              v-for="(imgUrl, index) in getImageUrls(message.content)"
              :key="index"
              class="relative rounded-lg overflow-hidden border border-border shadow-sm w-[120px] h-[120px]"
            >
              <img
                :src="imgUrl"
                :alt="`图片 ${index + 1}`"
                class="w-full h-full object-cover cursor-pointer hover:opacity-90 transition-opacity"
                @click="handleImageClick(imgUrl)"
              />
            </div>
          </div>
        </div>
        <div class="mt-1 mr-1 text-xs font-normal text-muted-foreground/60 flex items-center gap-2 justify-end">
          <span v-if="message.timestamp" class="text-[10px] opacity-70 font-normal">
            {{ formatTime(message.timestamp) }}
          </span>
          <button @click="handleCopy"
            class="opacity-0 group-hover:opacity-70 transition-opacity p-1 hover:bg-muted/60 rounded text-muted-foreground/70 hover:text-muted-foreground"
            :title="copied ? '已复制' : '复制内容'">
            <Check v-if="copied" class="w-3 h-3 text-green-500" />
            <Copy v-else class="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>

    <!-- 任务分析消息 -->
    <div
      v-else-if="message.role === 'assistant' && (message.type === 'task_analysis' || message.message_type === 'task_analysis')"
      class="flex flex-row items-start px-4"
      :class="hideAssistantAvatar ? 'gap-1' : 'gap-3'">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="hideAssistantAvatar ? 'w-0' : 'w-8'" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="w-full">
          <TaskAnalysisMessage :content="message.content" :isStreaming="isStreaming" :timestamp="message.timestamp" />
        </div>
      </div>
    </div>

    <div
      v-else-if="message.role === 'assistant' && (message.type === 'reasoning_content' || message.message_type === 'reasoning_content')"
      class="flex flex-row items-start px-4"
      :class="hideAssistantAvatar ? 'gap-1' : 'gap-3'">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="hideAssistantAvatar ? 'w-0' : 'w-8'" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="w-full">
          <ReasoningContentMessage :content="message.content" :isStreaming="isStreaming" :timestamp="message.timestamp" />
        </div>
      </div>
    </div>

    <!-- 助手消息 -->
    <div
      v-else-if="message.role === 'assistant' && !hasToolCalls && (message.content || getImageUrls(message.content).length > 0)"
      class="flex flex-row items-start px-4 group"
      :class="hideAssistantAvatar ? 'gap-1' : 'gap-3'">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="hideAssistantAvatar ? 'w-0' : 'w-8'" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="flex flex-col gap-1 w-full">
          <div
            v-if="getTextContent(message.content)"
            class="text-foreground/90 overflow-hidden break-words w-full font-sans text-sm leading-6">
            <MarkdownRendererWithPreview
              :content="formatMessageContent(getTextContent(message.content))"
              :components="markdownComponents"
              />
          </div>
          <!-- 图片内容 -->
          <div v-if="getImageUrls(message.content).length > 0" class="flex flex-wrap gap-2">
            <div
              v-for="(imgUrl, index) in getImageUrls(message.content)"
              :key="index"
              class="relative rounded-lg overflow-hidden border border-border shadow-sm w-[120px] h-[120px]"
            >
              <img
                :src="imgUrl"
                :alt="`图片 ${index + 1}`"
                class="w-full h-full object-cover cursor-pointer hover:opacity-90 transition-opacity"
                @click="handleImageClick(imgUrl)"
              />
            </div>
          </div>
        </div>
        <div v-if="!hideAssistantAvatar" class="mt-1 ml-1 text-xs font-normal text-muted-foreground/60 flex items-center gap-2">
          <span v-if="message.timestamp" class="text-[10px] opacity-70 font-normal">
            {{ formatTime(message.timestamp) }}
          </span>
          <button @click="handleCopy"
            class="opacity-0 group-hover:opacity-70 transition-opacity ml-2 p-1 hover:bg-muted/60 rounded text-muted-foreground/70 hover:text-muted-foreground"
            :title="copied ? '已复制' : '复制内容'">
            <Check v-if="copied" class="w-3 h-3 text-green-500" />
            <Copy v-else class="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>

    <!-- 工具渲染 -->
    <div
      v-else-if="hasToolCalls"
      class="flex flex-row items-start px-4"
      :class="hideAssistantAvatar ? 'gap-1' : 'gap-3'">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :toolName="getToolName(message)" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="hideAssistantAvatar ? 'w-0' : 'w-8'" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="tool-calls-bubble w-full" :class="{ 'custom-tool-bubble': isCustomToolMessage }">
          <div v-for="(toolCall, index) in message.tool_calls" :key="toolCall.id || index">
            <!-- Global Error Card -->
            <ToolErrorCard v-if="checkIsToolError(getParsedToolResult(toolCall))"
              :toolResult="getParsedToolResult(toolCall)" />
            <!-- Custom Tool Component -->
            <component
              v-else-if="isCustomTool(toolCall.function?.name)"
              :is="getToolComponent(toolCall.function?.name)"
              :toolCall="toolCall"
              :toolResult="getParsedToolResult(toolCall)"
              :message="message"
              :isLatest="index === message.tool_calls.length - 1 && isLatestMessage"
              :currentAgent="{ id: props.agentId, name: currentAgentName }"
              :openWorkbench="props.openWorkbench"
              @sendMessage="handleSendMessage"
              @openSubSession="emit('openSubSession', $event)"
              @click="handleToolClick"
            />
            <!-- Standard Tool Call Message -->
            <ToolCallMessage
              v-else
              :toolCall="toolCall"
              :toolResult="getParsedToolResult(toolCall)"
              :timestamp="message.timestamp"
              :isCancelled="message.cancelledToolCalls?.includes(toolCall.id)"
              :cancelledReason="message.cancelledToolCalls?.includes(toolCall.id) ? '已取消' : ''"
              @click="handleToolClick"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Tool Details Modal -->
    <ToolDetailsPanel :open="showToolDetails" @update:open="showToolDetails = $event"
      :tool-execution="selectedToolExecution" :tool-result="toolResult" />

  </div>
</template>

<script setup>
import { computed, h, ref, onMounted, watch } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import MessageAvatar from './MessageAvatar.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import MarkdownRendererWithPreview from './MarkdownRendererWithPreview.vue'
import EChartsRenderer from './EChartsRenderer.vue'
import SyntaxHighlighter from './SyntaxHighlighter.vue'
import TokenUsage from './TokenUsage.vue'
import { Terminal, FileText, Search, Zap, Copy, Check, Image } from 'lucide-vue-next'
import { getMessageLabel } from '@/utils/messageLabels'
import ToolErrorCard from './tools/ToolErrorCard.vue'
import ToolDefaultCard from './tools/ToolDefaultCard.vue'
import ToolCallMessage from './ToolCallMessage.vue'
import ToolDetailsPanel from './tools/ToolDetailsPanel.vue'
import TaskAnalysisMessage from './TaskAnalysisMessage.vue'
import ReasoningContentMessage from './ReasoningContentMessage.vue'
import AgentCardMessage from './tools/AgentCardMessage.vue'
import SysDelegateTaskMessage from './tools/SysDelegateTaskMessage.vue'
import SysFinishTaskMessage from './tools/SysFinishTaskMessage.vue'
import TodoTaskMessage from './tools/TodoTaskMessage.vue'
import QuestionnaireCard from './tools/QuestionnaireCard.vue'
import { useWorkbenchStore } from '@/stores/workbench.js'

// Custom Tools
const TOOL_COMPONENT_MAP = {
  sys_spawn_agent: AgentCardMessage,
  sys_delegate_task: SysDelegateTaskMessage,
  sys_finish_task: SysFinishTaskMessage,
  todo_write: TodoTaskMessage,
  questionnaire: QuestionnaireCard,
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
  },
  agentId: {
    type: String,
    default: ''
  },
  hideAssistantAvatar: {
    type: Boolean,
    default: null
  },
  openWorkbench: {
    type: Function,
    default: null
  },
  extractWorkbenchItems: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['downloadFile', 'toolClick', 'sendMessage', 'openSubSession'])

const { t } = useLanguage()
const workbenchStore = useWorkbenchStore()
const hideAssistantAvatar = computed(() => (
  props.hideAssistantAvatar === true && props.message.role === 'assistant'
))

const showAssistantAvatar = computed(() => {
  if (props.message.role !== 'assistant') return false
  if (props.hideAssistantAvatar === true) return false
  if (props.hideAssistantAvatar === false) return true
  if (hideAssistantAvatar.value) return false

  for (let i = props.messageIndex - 1; i >= 0; i -= 1) {
    const prev = props.messages?.[i]
    if (!prev) continue
    if (prev.role === 'tool') continue
    if (prev.type === 'token_usage' || prev.message_type === 'token_usage') continue
    return prev.role !== 'assistant'
  }
  return true
})

const currentAgentName = computed(() => {
  return props.message.agent_name || t('chat.currentAgent')
})

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

// 从多模态内容中提取文本
const getTextContent = (content) => {
  if (!content) return ''
  // 如果是字符串，直接返回
  if (typeof content === 'string') return content
  // 如果是数组，提取所有文本类型的内容
  if (Array.isArray(content)) {
    const textParts = content
      .filter(item => item.type === 'text' && item.text)
      .map(item => item.text)
    return textParts.join('\n')
  }
  return ''
}

// 从多模态内容中提取图片 URL
const getImageUrls = (content) => {
  if (!content || typeof content === 'string') return []
  // 如果是数组，提取所有图片类型的 URL
  if (Array.isArray(content)) {
    return content
      .filter(item => item.type === 'image_url' && item.image_url?.url)
      .map(item => item.image_url.url)
  }
  return []
}

// 处理图片点击 - 打开浏览器
const handleImageClick = (url) => {
  if (!url) return
  window.open(url, '_blank')
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

const getLabel = ({ role, type, toolName }) => {
  return getMessageLabel({
    role,
    type,
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

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  if (isToday) {
    return `${hours}:${minutes}:${seconds}`
  } else {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
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

  if (props.openWorkbench) {
    props.openWorkbench({ toolCallId: toolCall.id, realtime: false })
    emit('toolClick', toolCall, result)
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

const copied = ref(false)

const handleCopy = async () => {
  const textToCopy = getTextContent(props.message.content)
  if (!textToCopy) return
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(textToCopy)
      copied.value = true
      setTimeout(() => {
        copied.value = false
      }, 2000)
    } else {
      // Fallback for browsers/environments where clipboard API is not available (e.g. non-secure context)
      const textArea = document.createElement('textarea')
      textArea.value = textToCopy
      textArea.style.position = 'fixed'
      textArea.style.left = '-9999px'
      document.body.appendChild(textArea)
      textArea.focus()
      textArea.select()

      const successful = document.execCommand('copy')
      document.body.removeChild(textArea)

      if (successful) {
        copied.value = true
        setTimeout(() => {
          copied.value = false
        }, 2000)
      } else {
        console.error('Fallback copy method failed')
      }
    }
  } catch (err) {
    console.error('Failed to copy text: ', err)
  }
}

const getToolComponent = (toolName) => {
  if (!toolName) return ToolDefaultCard
  return TOOL_COMPONENT_MAP[toolName] || ToolDefaultCard
}

const isCustomTool = (toolName) => {
  if (!toolName) return false
  return !!TOOL_COMPONENT_MAP[toolName]
}

// 自动提取并推送到工作台
onMounted(() => {
  if (!props.extractWorkbenchItems) return

  // 1. 处理工具调用结果消息 (role='tool')
  if (props.message.role === 'tool' && props.message.tool_call_id) {
    // 将 Proxy 转换为普通对象
    const plainToolResult = JSON.parse(JSON.stringify(props.message))
    workbenchStore.updateToolResult(props.message.tool_call_id, plainToolResult)
    return
  }

  // 2. 提取工具调用、文件引用和代码块
  // 使用 props.agentId 或 message.agent_id 作为 fallback
  const effectiveAgentId = props.agentId || props.message.agent_id
  workbenchStore.extractFromMessage(props.message, effectiveAgentId)
})

// 监听消息变化（用于流式输出）
watch(() => props.message, (newMessage) => {
  if (!newMessage) return
  if (!props.extractWorkbenchItems) return

  // 1. 实时提取新出现的工具调用、文件引用和代码块
  // 使用 props.agentId 或 message.agent_id 作为 fallback
  const effectiveAgentId = props.agentId || newMessage.agent_id
  workbenchStore.extractFromMessage(newMessage, effectiveAgentId)

  // 2. 实时更新工具结果
  if (newMessage.tool_calls && newMessage.tool_calls.length > 0) {
    newMessage.tool_calls.forEach((toolCall) => {
      const toolResult = getParsedToolResult(toolCall)
      if (toolResult) {
        const plainToolResult = JSON.parse(JSON.stringify(toolResult))
        workbenchStore.updateToolResult(toolCall.id, plainToolResult)
      }
    })
  }
}, { deep: true })

watch(() => props.agentId, (newAgentId) => {
  if (!newAgentId || !props.message) return
  if (!props.extractWorkbenchItems) return

  // agent 详情稍后返回时，重新提取一次，补齐已存在 workbench item 的 agentId。
  workbenchStore.extractFromMessage(props.message, newAgentId)
})

</script>
