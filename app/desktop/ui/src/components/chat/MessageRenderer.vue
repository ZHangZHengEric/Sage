<template>
  <div v-if="shouldRenderMessage" class="flex flex-col gap-6 mb-6">
    <!-- 错误消息 -->
    <div v-if="isErrorMessage" class="flex flex-row gap-4 px-4">
      <div class="flex-none">
        <MessageAvatar messageType="error" role="assistant" :agentId="agentId" />
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
        <div class="mb-1 mr-1 text-xs font-medium text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity select-none flex items-center gap-2">
          <button 
            @click="handleCopy" 
            class="p-1 hover:bg-muted rounded text-muted-foreground hover:text-foreground"
            :title="copied ? '已复制' : '复制内容'"
          >
            <Check v-if="copied" class="w-3 h-3 text-green-500" />
            <Copy v-else class="w-3 h-3" />
          </button>
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
        <MessageAvatar :messageType="message.message_type" role="assistant" :agentId="agentId" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="w-full">
           <TaskAnalysisMessage 
             :content="message.content" 
             :isStreaming="isStreaming"
             :timestamp="message.timestamp"
           />
        </div>
      </div>
    </div>

    <!-- 助手消息 -->
    <div v-else-if="message.role === 'assistant' && !hasToolCalls && message.content" class="flex flex-row items-start gap-3 px-4 group" data-message-type="assistant">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.message_type" role="assistant" :agentId="agentId" />
      </div>
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
        <div class="mb-1 ml-1 text-xs font-medium text-muted-foreground flex items-center gap-2">
          {{ getLabel({ role: 'assistant', type: message.type, messageType: message.message_type }) }}
          <span v-if="message.timestamp" class="text-[10px] opacity-60 font-normal">
            {{ formatTime(message.timestamp) }}
          </span>
          <button 
            @click="handleCopy" 
            class="opacity-0 group-hover:opacity-100 transition-opacity ml-2 p-1 hover:bg-muted rounded text-muted-foreground hover:text-foreground"
            :title="copied ? '已复制' : '复制内容'"
          >
            <Check v-if="copied" class="w-3 h-3 text-green-500" />
            <Copy v-else class="w-3 h-3" />
          </button>
        </div>
        <div class="text-foreground/90 overflow-hidden break-words w-full text-[15px] leading-7 font-sans py-1">
          <MarkdownRendererWithPreview
            :content="formatMessageContent(message.content)"
          />
        </div>
      </div>
    </div>

    <!-- 工具渲染 -->
    <div v-else-if="hasToolCalls" class="flex flex-row items-start gap-3 px-4 mb-2" data-message-type="tool">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.message_type" role="assistant" :toolName="getToolName(message)" :agentId="agentId" />
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
              @openSubSession="emit('openSubSession', $event)"
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
import { computed, h, ref, onMounted, watch } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import MessageAvatar from './MessageAvatar.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import MarkdownRendererWithPreview from './MarkdownRendererWithPreview.vue'
import EChartsRenderer from './EChartsRenderer.vue'
import SyntaxHighlighter from './SyntaxHighlighter.vue'
import TokenUsage from './TokenUsage.vue'
import { Terminal, FileText, Search, Zap, Copy, Check } from 'lucide-vue-next'
import { getMessageLabel } from '@/utils/messageLabels'
import ToolErrorCard from './tools/ToolErrorCard.vue'
import ToolDefaultCard from './tools/ToolDefaultCard.vue'
import ToolDetailsPanel from './tools/ToolDetailsPanel.vue'
import TaskAnalysisMessage from './TaskAnalysisMessage.vue'
import AgentCardMessage from './tools/AgentCardMessage.vue'
import SysDelegateTaskMessage from './tools/SysDelegateTaskMessage.vue'
import TodoTaskMessage from './tools/TodoTaskMessage.vue'
import { useWorkbenchStore } from '../../stores/workbench.js'

// Custom Tools
const TOOL_COMPONENT_MAP = {
  sys_spawn_agent: AgentCardMessage,
  sys_delegate_task: SysDelegateTaskMessage,
  todo_write: TodoTaskMessage,
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
  openWorkbench: {
    type: Function,
    default: null
  }
})

const emit = defineEmits(['downloadFile', 'toolClick', 'sendMessage', 'openSubSession'])

const { t } = useLanguage()
const workbenchStore = useWorkbenchStore()

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
  const hasCalls = props.message.tool_calls && Array.isArray(props.message.tool_calls) && props.message.tool_calls.length > 0
  console.log('MessageRenderer - role:', props.message.role, 'hasToolCalls:', hasCalls, 'content:', props.message.content?.substring(0, 100))
  return hasCalls
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
  
  console.log('[MessageRenderer] getToolResult looking for:', toolCall.id, 'messageIndex:', props.messageIndex, 'total messages:', props.messages.length)
  
  // 在后续消息中查找对应的工具结果
  for (let i = props.messageIndex + 1; i < props.messages.length; i++) {
    const msg = props.messages[i]
    console.log('[MessageRenderer] Checking message', i, 'role:', msg.role, 'tool_call_id:', msg.tool_call_id)
    if (msg.role === 'tool' && msg.tool_call_id === toolCall.id) {
      console.log('[MessageRenderer] Found tool result for:', toolCall.id)
      return msg
    }
  }
  
  // 如果没找到，检查当前消息是否包含工具结果（某些格式）
  const currentMsg = props.messages[props.messageIndex]
  if (currentMsg && currentMsg.tool_results) {
    const toolResult = currentMsg.tool_results.find(r => r.tool_call_id === toolCall.id)
    if (toolResult) {
      console.log('[MessageRenderer] Found tool result in current message tool_results:', toolCall.id)
      return toolResult
    }
  }
  
  console.log('[MessageRenderer] Tool result not found for:', toolCall.id)
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

  // 使用统一的 openWorkbench 方法
  if (props.openWorkbench) {
    props.openWorkbench({ toolCallId: toolCall.id, realtime: false })
  }

  // 保留原来的弹窗逻辑（代码可以保留）
  selectedToolExecution.value = toolCall
  toolResult.value = result
  // showToolDetails.value = true  // 注释掉弹窗

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
  if (!props.message.content) return
  try {
    await navigator.clipboard.writeText(props.message.content)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy text: ', err)
  }
}

const getToolComponent = (toolName) => {
  if (!toolName) return ToolDefaultCard
  return TOOL_COMPONENT_MAP[toolName] || ToolDefaultCard
}

// 发送工作台事件
onMounted(() => {
  const messageId = props.message.message_id || props.message.id
  const sessionId = props.message.session_id

  console.log('[MessageRenderer] onMounted, messageId:', messageId, 'role:', props.message.role, 'tool_calls:', props.message.tool_calls?.length)

  // 处理工具结果消息（role='tool'）
  if (props.message.role === 'tool' && props.message.tool_call_id) {
    console.log('[MessageRenderer] Processing tool result message:', messageId, 'tool_call_id:', props.message.tool_call_id)
    // 更新工作台中的工具结果
    const plainToolResult = JSON.parse(JSON.stringify(props.message))
    const updateResult = workbenchStore.updateToolResult(props.message.tool_call_id, plainToolResult)
    console.log('[MessageRenderer] updateToolResult for tool message:', props.message.tool_call_id, 'result:', updateResult)
    return
  }

  // 只处理助手消息和工具调用
  if (props.message.role !== 'assistant') return

  // 检查该消息的工作台项是否已经添加过
  const existingItems = workbenchStore.items.filter(item =>
    item.messageId === messageId && item.sessionId === sessionId
  )

  if (existingItems.length > 0) {
    console.log('[MessageRenderer] Workbench items already exist for message:', messageId)
    return
  }

  const timestamp = props.message.timestamp || Date.now()

  // 发送工具调用事件
  if (props.message.tool_calls && props.message.tool_calls.length > 0) {
    console.log('[MessageRenderer] Adding tool_calls to workbench:', props.message.tool_calls.length)
    props.message.tool_calls.forEach((toolCall, index) => {
      console.log(`[MessageRenderer] Adding tool_call ${index}:`, toolCall.id)
      // 注意：不在 onMounted 中传递 toolResult，因为实时流中工具结果还没到达
      // toolResult 会在后续更新
      workbenchStore.addItem({
        type: 'tool_call',
        role: 'assistant',
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId,
        data: toolCall
        // toolResult 会在 watch 中更新
      })
    })
  }

  // 发送文件引用事件
  const fileMatches = extractFileReferences(props.message.content)
  fileMatches.forEach((file) => {
    workbenchStore.addItem({
      type: 'file',
      role: 'assistant',
      timestamp: timestamp,
      sessionId: sessionId,
      messageId: messageId,
      data: file
    })
  })

  // 发送代码块事件
  const codeBlocks = extractCodeBlocks(props.message.content)
  codeBlocks.forEach((code) => {
    workbenchStore.addItem({
      type: 'code',
      role: 'assistant',
      timestamp: timestamp,
      sessionId: sessionId,
      messageId: messageId,
      data: code
    })
  })
})

// 监听消息变化，更新工具结果
watch(() => props.message, (newMessage) => {
  console.log('[MessageRenderer] Watch triggered, message:', newMessage?.message_id, 'tool_calls:', newMessage?.tool_calls?.length)

  if (!newMessage?.tool_calls || newMessage.tool_calls.length === 0) {
    console.log('[MessageRenderer] No tool_calls, skipping')
    return
  }

  newMessage.tool_calls.forEach((toolCall) => {
    const toolResult = getParsedToolResult(toolCall)
    console.log('[MessageRenderer] toolCall.id:', toolCall.id, 'toolResult:', toolResult)
    if (toolResult) {
      // 将 Proxy 转换为普通对象
      const plainToolResult = JSON.parse(JSON.stringify(toolResult))
      console.log('[MessageRenderer] Plain toolResult:', plainToolResult)
      console.log('[MessageRenderer] typeof plainToolResult:', typeof plainToolResult)
      console.log('[MessageRenderer] plainToolResult keys:', Object.keys(plainToolResult))
      // 更新工作台中的工具结果
      console.log('[MessageRenderer] Calling updateToolResult with id:', toolCall.id, 'result:', plainToolResult)
      const updateResult = workbenchStore.updateToolResult(toolCall.id, plainToolResult)
      console.log('[MessageRenderer] updateToolResult returned:', updateResult)
    }
  })
}, { deep: true, immediate: true })

// 辅助函数：提取文件引用
function extractFileReferences(content) {
  if (!content) return []
  const files = []
  const markdownRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match

  while ((match = markdownRegex.exec(content)) !== null) {
    let path = match[2]
    const fileName = match[1]

    if (path.startsWith('file://')) {
      path = path.replace(/^file:\/\/\/?/i, '/')
    }

    // 过滤掉文件夹路径（以 / 结尾的路径）
    if (path.startsWith('/') && !path.endsWith('/')) {
      files.push({
        filePath: path,
        fileName: fileName || path.split('/').pop()
      })
    }
  }

  return files
}

// 辅助函数：提取代码块
function extractCodeBlocks(content) {
  if (!content) return []
  const codeBlocks = []
  const codeRegex = /```(\w+)?\n([\s\S]*?)```/g
  let match

  while ((match = codeRegex.exec(content)) !== null) {
    codeBlocks.push({
      language: match[1] || 'text',
      code: match[2].trim()
    })
  }

  return codeBlocks
}

</script>


