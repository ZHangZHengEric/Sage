<template>
  <div
    class="tool-call-message mb-2 cursor-pointer group"
    @click="handleClick"
  >
    <div class="flex items-center justify-start p-3 select-none transition-all hover:bg-muted/30 rounded-lg">
      <div class="header-content flex items-center gap-2 flex-1">
        <!-- 工具类型图标 -->
        <span class="type-icon flex items-center justify-center text-indigo-500">
          <component :is="getToolIcon(toolName)" class="w-4 h-4" />
        </span>
        <!-- 工具名称（多语言） -->
        <span class="header-text text-xs font-medium text-foreground">{{ getToolLabel(toolName, t) }}</span>
        <!-- 状态图标 -->
        <span class="status-icon flex items-center justify-center" :class="{ 'text-green-500': isCompleted, 'text-indigo-500': !isCompleted }">
          <Check v-if="isCompleted" class="w-4 h-4" />
          <Loader2 v-else class="w-4 h-4 animate-spin" />
        </span>
        <!-- 跳转箭头 -->
        <div class="expand-icon text-muted-foreground transition-transform duration-200 group-hover:translate-x-1" >
          <ChevronRight class="w-4 h-4" />
        </div>
        <!-- 时间戳 -->
        <span class="text-[10px] opacity-60 font-normal ml-2" v-if="timestamp">{{ formatTime(timestamp) }}</span>
        <!-- 点击查看详情提示 -->
        <span class="click-hint text-xs text-muted-foreground ml-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100">{{ t('common.viewDetails') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  Check,
  Loader2,
  ChevronRight,
  Zap,
  Terminal,
  FileText,
  Edit3,
  Save,
  Search,
  Globe,
  Image,
  Database,
  Settings,
  ListTodo,
  Mail,
  Code,
  Download,
  Minimize2
} from 'lucide-vue-next'
import { getToolLabel } from '@/utils/messageLabels'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [Object, String, Array],
    default: null
  },
  timestamp: {
    type: [Number, String],
    default: null
  }
})

const emit = defineEmits(['click'])

const { t } = useLanguage()

const toolName = computed(() => props.toolCall.function?.name || '')
const isCompleted = computed(() => !!props.toolResult)
const isError = computed(() => {
  if (!props.toolResult) return false
  if (typeof props.toolResult.content === 'object' && props.toolResult.content?.error === true) {
    return true
  }
  return false
})

// 工具图标映射
const toolIconMap = {
  // 文件操作
  'file_read': FileText,
  'file_write': Save,
  'file_update': Edit3,
  'view_files': FileText,
  'write_to_file': Save,
  'download_file_from_url': Download,
  'extract_text_from_non_text_file': FileText,
  // 代码相关
  'search_codebase': Search,
  'execute_shell_command': Terminal,
  'execute_python_code': Code,
  'execute_javascript_code': Code,
  'run_command': Terminal,
  // 网页相关
  'fetch_webpages': Globe,
  'web_search': Globe,
  'search_web_page': Globe,
  'fetch_webpage': Globe,
  'web_fetcher': Globe,
  // 图片相关
  'analyze_image': Image,
  'search_image_from_web': Image,
  'generate_image': Image,
  // 记忆相关
  'remember_user_memory': Database,
  'recall_user_memory': Database,
  'recall_user_memory_by_type': Database,
  'forget_user_memory': Database,
  'search_memory': Database,
  // 任务相关
  'todo_write': ListTodo,
  'todo_read': ListTodo,
  'list_tasks': ListTodo,
  'add_task': ListTodo,
  'delete_task': ListTodo,
  'complete_task': ListTodo,
  // IM相关
  'send_message_through_im': Mail,
  // 其他
  'load_skill': Settings,
  'ask_followup_question': Mail,
  'questionnaire': ListTodo,
  'list_dir': FileText,
  'search_by_regex': Search,
  'delete_file': FileText,
  'rename_file': FileText,
  'playwright_navigate': Globe,
  'playwright_click': Globe,
  'playwright_screenshot': Image,
  'playwright_fill': Globe,
  'playwright_hover': Globe,
  'playwright_evaluate': Code,
  // 压缩历史消息
  'compress_conversation_history': Minimize2,
}

const getToolIcon = (name) => {
  return toolIconMap[name] || Zap
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
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

const handleClick = () => {
  emit('click', props.toolCall, props.toolResult)
}
</script>
