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
      class="flex flex-row-reverse items-start gap-3 px-4 group min-w-0">
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
            <button @click="handleCopy"
              class="opacity-0 group-hover:opacity-70 transition-opacity p-1 hover:bg-muted/60 rounded text-muted-foreground/70 hover:text-muted-foreground"
              :title="copied ? '已复制' : '复制内容'">
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
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="w-full">
          <TaskAnalysisMessage :content="message.content" :isStreaming="isStreaming" :timestamp="message.timestamp" />
        </div>
      </div>
    </div>

    <div
      v-else-if="message.role === 'assistant' && (message.type === 'reasoning_content' || message.message_type === 'reasoning_content')"
      class="flex flex-row items-start px-4"
      :class="assistantRowGapClass">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
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
      :class="assistantRowGapClass">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="flex flex-col gap-1 w-full">
          <div
            v-if="getTextContent(message.content)"
            class="text-foreground/90 overflow-hidden break-words w-full font-sans text-sm leading-6">
            <MarkdownRendererWithPreview
              :content="formatMessageContent(getTextContent(message.content))"
              :components="markdownComponents"
              :message-id="message.message_id || message.id"
              />
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
      :class="assistantRowGapClass">
      <div v-if="showAssistantAvatar" class="flex-none">
        <MessageAvatar :messageType="message.message_type || message.type" role="assistant" :toolName="getToolName(message)" :agentId="agentId" />
      </div>
      <div v-else class="flex-none" :class="assistantAvatarSpacerClass" />
      <div class="flex flex-col items-start max-w-[85%] sm:max-w-[75%] w-full">
        <div class="tool-calls-bubble w-full" :class="{ 'custom-tool-bubble': isCustomToolMessage }">
          <div v-for="(toolCall, index) in visibleToolCalls" :key="toolCall.id || index">
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
              :isLatest="index === visibleToolCalls.length - 1 && isLatestMessage"
              :currentAgent="{ id: props.agentId, name: currentAgentName }"
              :openWorkbench="props.openWorkbench"
              @sendMessage="handleSendMessage"
              @openSubSession="emit('openSubSession', $event)"
              @click="handleToolClick($event, getParsedToolResult(toolCall), toolCall)"
            />
            <!-- Standard Tool Call Message -->
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
import { Terminal, FileText, Search, Zap, Copy, Check, Image, SquarePen, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { getMessageLabel, isTokenUsageMessage as isTokenUsageMessageValue } from '@/utils/messageLabels'
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
import {
  getRenderableContentItems,
  extractAttachmentName
} from '@/utils/multimodalContent.js'
import { parseToolJsonValue } from '@/utils/safeParseToolJson.js'
import { buildClipboardTextFromMessageContent, normalizeMessageContentForComposer } from '@/utils/composerFromMessageFlatten.js'

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
  if (typeof content === 'string') return content
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

// 统一渲染策略：把 multimodal content 中的所有 text part 拼接后交给 MarkdownRenderer，
// 它已经能渲染 http/https 图片（server-web）以及本地路径（desktop 通过 readFile）。
// 只有"没在文本里出现 markdown 引用"的孤立 image_url 才走兜底网格。
const orphanImageUrls = computed(() => {
  const items = getRenderableContentItems(props.message?.content)
  return items.filter(it => it.type === 'image_url').map(it => it.url)
})
const getAttachmentDisplayName = (url) => extractAttachmentName(url)

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

const handleToolClick = (rawToolCall, fallbackResult = null, fallbackToolCall = null) => {
  const toolCall = rawToolCall instanceof Event
    ? fallbackToolCall
    : (rawToolCall || fallbackToolCall)
  if (!toolCall) return

  const toolCallId = toolCall?.id || toolCall?.tool_call_id || null
  const messageId = props.message?.message_id || props.message?.id || null

  if (props.openWorkbench) {
    props.openWorkbench({ toolCallId, messageId, realtime: false })
    emit('toolClick', toolCall, fallbackResult)
    return
  }

  selectedToolExecution.value = toolCall
  toolResult.value = fallbackResult
  showToolDetails.value = true

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

  if (result.content != null && typeof result.content === 'string') {
    const parsed = parseToolJsonValue(result.content)
    if (parsed !== null) {
      return {
        ...result,
        content: parsed
      }
    }
    return result
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

const markCopiedBriefly = () => {
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 2000)
}

const copyPlainTextFallback = async (textToCopy) => {
  if (!textToCopy) return false
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(textToCopy)
      return true
    }
  } catch (err) {
    console.warn('navigator.clipboard.writeText failed:', err)
  }
  try {
    const textArea = document.createElement('textarea')
    textArea.value = textToCopy
    textArea.style.position = 'fixed'
    textArea.style.left = '-9999px'
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()

    const successful = document.execCommand('copy')
    document.body.removeChild(textArea)
    return successful
  } catch (err) {
    console.error('Fallback copy method failed:', err)
    return false
  }
}

const handleCopy = async () => {
  const contentNorm = normalizeMessageContentForComposer(props.message.content)
  const clip =
    buildClipboardTextFromMessageContent(contentNorm) ||
    getTextContent(contentNorm)
  if (!clip) return
  const ok = await copyPlainTextFallback(clip)
  if (!ok) {
    console.error('Failed to copy text')
    return
  }
  markCopiedBriefly()
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
  const messageId = props.message?.message_id || props.message?.id || null
  if (props.message.tool_calls && props.message.tool_calls.length > 0) {
    props.message.tool_calls.forEach((toolCall, index) => {
      const toolStableKey = messageId ? `tool:${messageId}:${index}` : (toolCall.id ? `tool:${toolCall.id}` : null)
      const existingToolItem = workbenchStore.items.find(item =>
        item.type === 'tool_call' && (
          item.data?.id === toolCall.id ||
          item.data?.tool_call_id === toolCall.id ||
          (toolStableKey && item.stableKey === toolStableKey)
        )
      )
      if (existingToolItem) return
      workbenchStore.addItem({
        type: 'tool_call',
        role: props.message.role,
        timestamp: props.message.timestamp || Date.now(),
        sessionId: props.message.session_id || null,
        messageId,
        agentId: effectiveAgentId,
        stableKey: toolStableKey,
        data: toolCall,
        toolResult: null
      })
    })
  }
  workbenchStore.extractFromMessage(props.message, effectiveAgentId)
})

// 监听消息变化（用于流式输出）
watch(() => props.message, (newMessage) => {
  if (!newMessage) return
  if (!props.extractWorkbenchItems) return

  // 1. 实时提取新出现的工具调用、文件引用和代码块
  // 使用 props.agentId 或 message.agent_id 作为 fallback
  const effectiveAgentId = props.agentId || newMessage.agent_id
  const messageId = newMessage?.message_id || newMessage?.id || null
  if (newMessage.tool_calls && newMessage.tool_calls.length > 0) {
    newMessage.tool_calls.forEach((toolCall, index) => {
      const toolStableKey = messageId ? `tool:${messageId}:${index}` : (toolCall.id ? `tool:${toolCall.id}` : null)
      const existingToolItem = workbenchStore.items.find(item =>
        item.type === 'tool_call' && (
          item.data?.id === toolCall.id ||
          item.data?.tool_call_id === toolCall.id ||
          (toolStableKey && item.stableKey === toolStableKey)
        )
      )
      if (existingToolItem) return
      workbenchStore.addItem({
        type: 'tool_call',
        role: newMessage.role,
        timestamp: newMessage.timestamp || Date.now(),
        sessionId: newMessage.session_id || null,
        messageId,
        agentId: effectiveAgentId,
        stableKey: toolStableKey,
        data: toolCall,
        toolResult: null
      })
    })
  }
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

watch(isEditingThisUserMessage, (isEditing) => {
  if (isEditing) {
    editingContent.value = getTextContent(props.message.content)
  }
})

</script>
