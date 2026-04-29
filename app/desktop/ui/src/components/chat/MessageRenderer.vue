<template>
  <div v-if="shouldRenderMessage" class="flex flex-col gap-1 mb-1">
    <!-- 循环熔断消息 -->
    <div v-if="isLoopBreakMessage" class="flex flex-row gap-4 px-4">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar messageType="loop_break" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none w-8" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
        <div class="mb-0.5 ml-1 text-xs font-medium text-amber-500/80">
          ⚠ {{ getLabel({ role: 'assistant', type: 'loop_break' }) }}
        </div>
        <div class="bg-amber-500/8 text-amber-700 dark:text-amber-400 border border-amber-400/20 rounded-[20px] rounded-tl-[4px] px-4 py-2.5 shadow-sm overflow-hidden break-words w-full">
          <div class="text-sm leading-6 font-medium">{{ message.content }}</div>
        </div>
      </div>
    </div>

    <!-- 错误消息 -->
    <div v-else-if="isErrorMessage" class="flex flex-row gap-4 px-4">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar messageType="error" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none w-8" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%]">
        <div class="mb-0.5 ml-1 text-xs font-medium text-muted-foreground">
          {{ getLabel({ role: 'assistant', type: 'error' }) }}
        </div>
        <div class="bg-destructive/5 text-destructive border border-destructive/10 rounded-[20px] rounded-tl-[4px] px-4 py-2.5 shadow-sm overflow-hidden break-words w-full">
          <div class="opacity-90 text-sm leading-6 font-medium">{{ message.content || t('error.unknown') }}</div>
        </div>
      </div>
    </div>

    <!-- Token 使用消息 -->
    <div v-else-if="isTokenUsageMessage && tokenUsageData" class="flex justify-center px-4 my-2">
      <TokenUsage :token-usage="tokenUsageData" />
    </div>

    <!-- 用户消息 -->
    <div v-else-if="message.role === 'user' && message.message_type !== 'guide'" class="flex flex-row-reverse items-start gap-3 px-4 group min-w-0">
      <div class="flex-none mt-1">
        <MessageAvatar :messageType="message.type || message.message_type" role="user" />
      </div>
      <div class="flex flex-col items-end max-w-[80%] sm:max-w-[70%] min-w-0">
        <div v-if="isEditingThisUserMessage" class="w-full rounded-[20px] rounded-tr-[4px] border border-border/70 bg-secondary/80 px-4 py-3 shadow-sm">
          <textarea
            v-model="editingContent"
            rows="3"
            class="w-full resize-none bg-transparent text-sm leading-6 text-secondary-foreground outline-none"
          />
          <div class="mt-3 flex items-center justify-end gap-2">
            <button
              type="button"
              class="rounded-full border border-border/70 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/50"
              @click="handleCancelEditUserMessage"
            >
              {{ t('common.cancel') || '取消' }}
            </button>
            <button
              type="button"
              class="rounded-full bg-primary px-3 py-1.5 text-xs text-primary-foreground disabled:opacity-50"
              :disabled="!editingContent.trim()"
              @click="handleSubmitEditUserMessage"
            >
              {{ t('common.send') || '发送' }}
            </button>
          </div>
        </div>
        <div v-else class="flex flex-col gap-1 items-end max-w-full min-w-0">
          <div
            v-if="getTextContent(message.content)"
            class="relative bg-secondary/80 text-secondary-foreground rounded-[20px] rounded-tr-[4px] px-4 py-2.5 shadow-sm break-words break-all overflow-hidden text-sm leading-6 tracking-wide font-sans max-w-full min-w-0"
          >
            <div
              class="overflow-hidden transition-[max-height] duration-200 ease-out"
              :class="{ 'max-h-[200px]': isUserContentCollapsed && isUserContentLong }"
            >
              <MarkdownRenderer
                :content="formatMessageContent(getTextContent(message.content))"
              />
            </div>
            <!-- 折叠时底部渐隐遮罩，提示有更多内容 -->
            <div
              v-if="isUserContentCollapsed && isUserContentLong"
              class="pointer-events-none absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-secondary via-secondary/80 to-transparent"
            ></div>
          </div>
          <!-- 兜底：老消息没有 markdown 引用、image_url 单独成段时，把孤立图片以网格呈现 -->
          <div v-if="orphanImageUrls.length > 0" class="flex flex-wrap gap-2">
            <div
              v-for="(imgUrl, index) in orphanImageUrls"
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
        <div class="mt-1 mr-1 w-full flex items-center gap-2 text-xs font-normal text-muted-foreground/60">
          <!-- 长消息折叠开关：与时间在同一行，靠最左侧 -->
          <button
            v-if="isUserContentLong"
            type="button"
            class="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            @click="isUserContentCollapsed = !isUserContentCollapsed"
          >
            <ChevronDown v-if="isUserContentCollapsed" class="w-3 h-3" />
            <ChevronUp v-else class="w-3 h-3" />
            {{ isUserContentCollapsed ? (t('chat.showMore') || '显示更多') : (t('chat.collapse') || '收起') }}
          </button>
          <div class="ml-auto flex items-center gap-2">
            <span v-if="message.timestamp" class="text-[10px] opacity-70 font-normal">
              {{ formatTime(message.timestamp) }}
            </span>
            <button
              @click="handleCopy"
              class="opacity-0 group-hover:opacity-70 transition-opacity p-1 hover:bg-muted/60 rounded text-muted-foreground/70 hover:text-muted-foreground"
              :title="copied ? '已复制' : '复制内容'"
            >
              <Check v-if="copied" class="w-3 h-3 text-green-500" />
              <Copy v-else class="w-3 h-3" />
            </button>
            <button
              v-if="isEditableUserMessage && !isEditingThisUserMessage"
              type="button"
              class="opacity-0 group-hover:opacity-70 transition-opacity p-1 hover:bg-muted/60 rounded text-muted-foreground/70 hover:text-muted-foreground"
              :title="t('chat.editLastUserMessage') || '编辑并重试'"
              @click="handleStartEditUserMessage"
            >
              <SquarePen class="w-3 h-3" />
            </button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 任务分析消息 -->
    <div
      v-else-if="message.role === 'assistant' && (message.type === 'task_analysis' || message.message_type === 'task_analysis')"
      class="flex flex-row items-start px-4"
      :class="assistantRowGapClass">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
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

    <!-- 推理思考消息 -->
    <div
      v-else-if="message.role === 'assistant' && (message.type === 'reasoning_content' || message.message_type === 'reasoning_content')"
      class="flex flex-row items-start px-4"
      :class="assistantRowGapClass">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="w-full">
           <ReasoningContentMessage
             :content="message.content"
             :isStreaming="isStreaming"
             :timestamp="message.timestamp"
           />
        </div>
      </div>
    </div>

    <!-- 助手消息 -->
    <div
      v-else-if="message.role === 'assistant' && !hasToolCalls && (message.content || getImageUrls(message.content).length > 0)"
      class="flex flex-row items-start px-4 group"
      :class="assistantRowGapClass"
      data-message-type="assistant">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="flex flex-col gap-1 w-full">
          <div
            v-if="getTextContent(message.content)"
            class="text-foreground/90 overflow-hidden break-words w-full font-sans text-sm leading-6">
            <MarkdownRendererWithPreview
              :content="formatMessageContent(getTextContent(message.content))"
              :message-id="message.message_id || message.id"
              :agent-id="agentId"
            />
          </div>
          <!-- 兜底：没有 markdown 引用的孤立 image_url -->
          <div v-if="orphanImageUrls.length > 0" class="flex flex-wrap gap-2">
            <div
              v-for="(imgUrl, index) in orphanImageUrls"
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
          <button
            @click="handleCopy"
            class="opacity-0 group-hover:opacity-70 transition-opacity ml-2 p-1 hover:bg-muted/60 rounded text-muted-foreground/70 hover:text-muted-foreground"
            :title="copied ? '已复制' : '复制内容'"
          >
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
      :class="assistantRowGapClass"
      data-message-type="tool">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type" role="assistant" :toolName="getToolName(message)" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
         <div class="tool-calls-bubble w-full" :class="{ 'custom-tool-bubble': isCustomToolMessage }">
           <div v-for="(toolCall, index) in visibleToolCalls" :key="toolCall.id || index">
             <!-- Global Error Card -->
             <ToolErrorCard v-if="checkIsToolError(getParsedToolResult(toolCall))" :toolResult="getParsedToolResult(toolCall)" />
             <!-- Custom Tool Component (定制化工具) -->
             <component
               v-else-if="isCustomTool(toolCall.function?.name)"
               :is="getToolComponent(toolCall.function?.name)"
               :toolCall="toolCall"
               :toolResult="getParsedToolResult(toolCall)"
               :message="message"
               :isLatest="index === visibleToolCalls.length - 1 && isLatestMessage"
               :currentAgent="{ id: props.agentId, name: currentAgentName }"
               :openWorkbench="props.openWorkbench"
               @sendMessage="handleSendMessage"
              @openSubSession="emit('openSubSession', $event)"
              @click="handleToolClick($event, getParsedToolResult(toolCall), toolCall)"
            />
            <!-- Standard Tool Call Message (普通工具调用) -->
            <ToolCallMessage
              v-else
              :toolCall="toolCall"
              :toolResult="getParsedToolResult(toolCall)"
              :timestamp="message.timestamp"
              :isCancelled="message.cancelledToolCalls?.includes(toolCall.id)"
              :cancelledReason="message.cancelledToolCalls?.includes(toolCall.id) ? '已取消' : ''"
              @click="handleToolClick($event, getParsedToolResult(toolCall), toolCall)"
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
import { Terminal, FileText, Search, Zap, Copy, Check, SquarePen, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { getMessageLabel, isTokenUsageMessage as isTokenUsageMessageValue } from '@/utils/messageLabels'
import ToolErrorCard from './tools/ToolErrorCard.vue'
import ToolDefaultCard from './tools/ToolDefaultCard.vue'
import ToolCallMessage from './ToolCallMessage.vue'
import ToolDetailsPanel from './tools/ToolDetailsPanel.vue'
import TaskAnalysisMessage from './TaskAnalysisMessage.vue'
import ReasoningContentMessage from './ReasoningContentMessage.vue'
import AgentCardMessage from './tools/AgentCardMessage.vue'
import SysDelegateTaskMessage from './tools/SysDelegateTaskMessage.vue'
import TodoTaskMessage from './tools/TodoTaskMessage.vue'
import QuestionnaireCard from './tools/QuestionnaireCard.vue'
import { useWorkbenchStore } from '../../stores/workbench.js'
import { textHasMarkdownImageRefForUrl } from '../../utils/multimodalContent.js'
import { open } from '@tauri-apps/plugin-shell'
import { isAbsoluteLocalPath, isRelativeWorkspacePath, normalizeFileReference, resolveAgentWorkspacePath } from '@/utils/agentWorkspacePath'

// Custom Tools
const TOOL_COMPONENT_MAP = {
  sys_spawn_agent: AgentCardMessage,
  sys_delegate_task: SysDelegateTaskMessage,
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
    default: true  // 默认提取工作台项目
  },
  editableUserMessageId: {
    type: String,
    default: null
  },
  editingUserMessageId: {
    type: String,
    default: null
  }
})

const emit = defineEmits([
  'downloadFile',
  'toolClick',
  'sendMessage',
  'openSubSession',
  'startEditUserMessage',
  'cancelEditUserMessage',
  'submitEditUserMessage'
])

const { t } = useLanguage()
const workbenchStore = useWorkbenchStore()
const editingContent = ref('')
const currentMessageId = computed(() => props.message.message_id || props.message.id || null)
const isEditableUserMessage = computed(() => (
  props.message.role === 'user' &&
  currentMessageId.value &&
  currentMessageId.value === props.editableUserMessageId
))
const isEditingThisUserMessage = computed(() => (
  isEditableUserMessage.value &&
  currentMessageId.value === props.editingUserMessageId
))

// 用户消息「显示更多 / 收起」状态：超过阈值时折叠到首屏，类似 codex 风格
const USER_LONG_THRESHOLD_CHARS = 240
const USER_LONG_THRESHOLD_LINES = 8
const userContentText = computed(() => {
  if (props.message.role !== 'user') return ''
  return getTextContent(props.message.content) || ''
})
const isUserContentLong = computed(() => {
  const text = userContentText.value
  if (!text) return false
  if (text.length > USER_LONG_THRESHOLD_CHARS) return true
  if (text.split('\n').length > USER_LONG_THRESHOLD_LINES) return true
  return false
})
const isUserContentCollapsed = ref(true)
const hideAssistantAvatar = computed(() => (
  props.hideAssistantAvatar === true && props.message.role === 'assistant'
))
const assistantRowGapClass = computed(() => (
  props.message.role === 'assistant' ? 'gap-3' : (hideAssistantAvatar.value ? 'gap-1' : 'gap-3')
))
const assistantAvatarSpacerClass = computed(() => (
  props.message.role === 'assistant' ? 'w-8' : (hideAssistantAvatar.value ? 'w-0' : 'w-8')
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
    if (isTokenUsageMessageValue(prev)) continue
    return prev.role !== 'assistant'
  }
  return true
})

// 当前 Agent 名称
const currentAgentName = computed(() => {
  // Try to get from message metadata or use default
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

const isLoopBreakMessage = computed(() => {
  return props.message.type === 'loop_break' || props.message.message_type === 'loop_break'
})

const isErrorMessage = computed(() => {
  return props.message.type === 'error' || props.message.message_type === 'error'
})

const isTokenUsageMessage = computed(() => {
  return isTokenUsageMessageValue(props.message)
})

const tokenUsageData = computed(() => {
  return props.message?.metadata?.token_usage || null
})

// 协议性内置工具：仅作为 agent 控制信号，不在对话中渲染（数据仍保留在 message 内）
const HIDDEN_TOOL_NAMES = new Set(['turn_status'])

const visibleToolCalls = computed(() => {
  if (!props.message.tool_calls || !Array.isArray(props.message.tool_calls)) return []
  return props.message.tool_calls.filter(tc => !HIDDEN_TOOL_NAMES.has(tc?.function?.name))
})

const hasToolCalls = computed(() => visibleToolCalls.value.length > 0)


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

// 桌面端 sidecar 已经把上传文件以 http://127.0.0.1:<port>/api/oss/file/... 暴露出来，
// 前端图片 src 与 server 端逻辑完全一致，无需再做 Tauri convertFileSrc 转换。
const handleImageClick = async (url) => {
  if (!url) return
  try {
    await open(url)
  } catch (err) {
    console.error('Failed to open URL:', err)
  }
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

// 已经在文本里以 markdown 引用方式呈现的 image_url 不再网格化重复显示，
// 只把"孤立的"image_url（老消息或只发了图片的情况）作为兜底网格渲染。
const orphanImageUrls = computed(() => {
  const allText = getTextContent(props.message?.content) || ''
  return getImageUrls(props.message?.content).filter(
    (url) => !textHasMarkdownImageRefForUrl(allText, url)
  )
})


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
    toolName,
    t
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

const handleToolClick = (rawToolCall, fallbackResult = null, fallbackToolCall = null) => {
  const toolCall = rawToolCall instanceof Event
    ? fallbackToolCall
    : (rawToolCall || fallbackToolCall)
  if (!toolCall) return

  const toolCallId = toolCall?.id || toolCall?.tool_call_id || null
  const messageId = props.message?.message_id || props.message?.id || null

  // 使用统一的 openWorkbench 方法
  if (props.openWorkbench) {
    props.openWorkbench({ toolCallId, messageId, realtime: false })
  }

  // 保留原来的弹窗逻辑（代码可以保留）
  selectedToolExecution.value = toolCall
  toolResult.value = fallbackResult
  // showToolDetails.value = true  // 注释掉弹窗

  emit('toolClick', toolCall, fallbackResult)
}

const handleDownloadFile = (filePath) => {
  emit('downloadFile', filePath)
}

const handleSendMessage = (text) => {
  emit('sendMessage', text)
}

const handleStartEditUserMessage = () => {
  if (!isEditableUserMessage.value) return
  editingContent.value = getTextContent(props.message.content)
  emit('startEditUserMessage', props.message)
}

const handleCancelEditUserMessage = () => {
  editingContent.value = getTextContent(props.message.content)
  emit('cancelEditUserMessage')
}

const handleSubmitEditUserMessage = () => {
  const content = editingContent.value.trim()
  if (!content) return
  emit('submitEditUserMessage', content)
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
    await navigator.clipboard.writeText(textToCopy)
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

// 判断是否为定制化工具
const isCustomTool = (toolName) => {
  if (!toolName) return false
  return !!TOOL_COMPONENT_MAP[toolName]
}

// 发送工作台事件
onMounted(async () => {
  const messageId = props.message.message_id || props.message.id
  const sessionId = props.message.session_id

  console.log('[MessageRenderer] onMounted, messageId:', messageId, 'role:', props.message.role, 'tool_calls:', props.message.tool_calls?.length, 'extractWorkbenchItems:', props.extractWorkbenchItems)

  // 如果不提取工作台项目，直接返回
  if (!props.extractWorkbenchItems) {
    console.log('[MessageRenderer] Skipping workbench extraction for message:', messageId)
    return
  }

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

  const timestamp = props.message.timestamp || Date.now()

  // 发送工具调用事件
  if (props.message.tool_calls && props.message.tool_calls.length > 0) {
    console.log('[MessageRenderer] Adding tool_calls to workbench:', props.message.tool_calls.length)
    props.message.tool_calls.forEach((toolCall, index) => {
      console.log(`[MessageRenderer] Adding tool_call ${index}:`, toolCall.id)
      const toolStableKey = messageId ? `tool:${messageId}:${index}` : (toolCall.id ? `tool:${toolCall.id}` : null)
      const existingToolItem = workbenchStore.items.find(item =>
        item.type === 'tool_call' && (
          item.data?.id === toolCall.id ||
          item.data?.tool_call_id === toolCall.id ||
          (toolStableKey && item.stableKey === toolStableKey)
        )
      )
      if (existingToolItem) {
        return
      }
      // 注意：不在 onMounted 中传递 toolResult，因为实时流中工具结果还没到达
      // toolResult 会在后续更新
      workbenchStore.addItem({
        type: 'tool_call',
        role: 'assistant',
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId,
        agent_id: props.agentId,
        agent_name: currentAgentName.value,
        stableKey: toolStableKey,
        data: toolCall
        // toolResult 会在 watch 中更新
      })
    })
  }

  // 发送文件引用事件
  const fileMatches = await extractFileReferences(props.message.content, props.agentId)
  fileMatches.forEach((file) => {
    const existingFileItem = workbenchStore.items.find(item =>
      item.messageId === messageId &&
      item.type === (file.isImage ? 'image' : 'file') &&
      (item.data?.filePath === file.filePath || item.data?.src === file.filePath)
    )
    if (existingFileItem) {
      return
    }
    // 图片文件使用 type: 'image'，其他文件使用 type: 'file'
    workbenchStore.addItem({
      type: file.isImage ? 'image' : 'file',
      role: 'assistant',
      timestamp: timestamp,
      sessionId: sessionId,
      messageId: messageId,
      data: file.isImage ? {
        src: file.filePath,
        alt: file.fileName,
        name: file.fileName
      } : file
    })
  })

  // 发送代码块事件
  const codeBlocks = extractCodeBlocks(props.message.content)
  codeBlocks.forEach((code) => {
    const existingCodeItem = workbenchStore.items.find(item =>
      item.messageId === messageId &&
      item.type === 'code' &&
      item.data?.code === code.code
    )
    if (existingCodeItem) {
      return
    }
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

// 监听消息变化，更新工具结果、文件引用、代码块（用于实时消息流）
watch(() => props.message, async (newMessage, oldMessage) => {
  console.log('[MessageRenderer] Watch triggered, message:', newMessage?.message_id, 'tool_calls:', newMessage?.tool_calls?.length)

  const messageId = newMessage?.message_id || newMessage?.id
  const sessionId = newMessage?.session_id
  const timestamp = newMessage?.timestamp || Date.now()

  // 1. 处理工具调用结果
  if (newMessage?.tool_calls && newMessage.tool_calls.length > 0) {
    newMessage.tool_calls.forEach((toolCall) => {
      // 流式场景下，tool_calls 可能在消息已挂载后才到达：
      // 先确保工作台存在对应 tool_call 卡片，再尝试更新结果。
      const toolIndex = newMessage.tool_calls.indexOf(toolCall)
      const toolStableKey = messageId ? `tool:${messageId}:${toolIndex}` : (toolCall.id ? `tool:${toolCall.id}` : null)
      const existingToolItem = workbenchStore.items.find(item =>
        item.type === 'tool_call' && (
          item.data?.id === toolCall.id ||
          item.data?.tool_call_id === toolCall.id ||
          (toolStableKey && item.stableKey === toolStableKey)
        )
      )
      if (!existingToolItem) {
        workbenchStore.addItem({
          type: 'tool_call',
          role: 'assistant',
          timestamp: timestamp,
          sessionId: sessionId,
          messageId: messageId,
          agent_id: props.agentId,
          agent_name: currentAgentName.value,
          stableKey: toolStableKey,
          data: toolCall
        })
      }

      const toolResult = getParsedToolResult(toolCall)
      console.log('[MessageRenderer] toolCall.id:', toolCall.id, 'toolResult:', toolResult)
      if (toolResult) {
        // 将 Proxy 转换为普通对象
        const plainToolResult = JSON.parse(JSON.stringify(toolResult))
        console.log('[MessageRenderer] Calling updateToolResult with id:', toolCall.id)
        workbenchStore.updateToolResult(toolCall.id, plainToolResult)
      }
    })
  }

  // 2. 处理文件引用（实时流中文件引用可能在消息更新时出现）
  if (newMessage?.content && newMessage.content !== oldMessage?.content) {
    const fileMatches = await extractFileReferences(newMessage.content, props.agentId)
    console.log('[MessageRenderer] Watch found file references:', fileMatches.length)
    fileMatches.forEach((file) => {
      // 检查该文件是否已经在该消息中添加过
      const existingFileItem = workbenchStore.items.find(item =>
        item.messageId === messageId &&
        item.type === (file.isImage ? 'image' : 'file') &&
        (item.data?.filePath === file.filePath || item.data?.src === file.filePath)
      )
      if (existingFileItem) {
        console.log('[MessageRenderer] File already exists in workbench for this message:', file.filePath)
        return
      }
      // 图片文件使用 type: 'image'，其他文件使用 type: 'file'
      workbenchStore.addItem({
        type: file.isImage ? 'image' : 'file',
        role: 'assistant',
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId,
        data: file.isImage ? {
          src: file.filePath,
          alt: file.fileName,
          name: file.fileName
        } : file
      })
    })
  }

  // 3. 处理代码块（实时流中代码块可能在消息更新时出现）
  if (newMessage?.content && newMessage.content !== oldMessage?.content) {
    const codeBlocks = extractCodeBlocks(newMessage.content)
    console.log('[MessageRenderer] Watch found code blocks:', codeBlocks.length)
    codeBlocks.forEach((code) => {
      // 检查该代码块是否已经在该消息中添加过
      const existingCodeItem = workbenchStore.items.find(item =>
        item.messageId === messageId &&
        item.type === 'code' &&
        item.data?.code === code.code
      )
      if (existingCodeItem) {
        console.log('[MessageRenderer] Code block already exists in workbench for this message:', code.language)
        return
      }
      workbenchStore.addItem({
        type: 'code',
        role: 'assistant',
        timestamp: timestamp,
        sessionId: sessionId,
        messageId: messageId,
        data: code
      })
    })
  }
}, { deep: true })

watch(isEditingThisUserMessage, (isEditing) => {
  if (isEditing) {
    editingContent.value = getTextContent(props.message.content)
  }
})

// 辅助函数：提取文件引用
async function extractFileReferences(content, agentId = '') {
  if (!content) return []
  const files = []
  const markdownRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match

  while ((match = markdownRegex.exec(content)) !== null) {
    let path = normalizeFileReference(match[2])
    const fileName = match[1]

    // 过滤掉文件夹路径（以 / 结尾的路径）
    const isWorkspaceRelative = !!agentId && isRelativeWorkspacePath(path)
    if ((isAbsoluteLocalPath(path) || isWorkspaceRelative) && !path.endsWith('/')) {
      // 判断是否为图片文件
      const imageExtensions = /\.(jpg|jpeg|png|gif|webp|svg|bmp|ico)$/i
      if (isWorkspaceRelative) {
        path = await resolveAgentWorkspacePath(path, agentId)
      }
      const isImage = imageExtensions.test(path)

      files.push({
        filePath: path,
        fileName: fileName || path.split('/').pop(),
        isImage: isImage
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

<style scoped>
/* SVG 预览样式 */
.svg-preview {
  background-color: hsl(var(--muted) / 0.3);
}
</style>
