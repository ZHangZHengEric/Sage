<template>
  <div
    class="tool-call-message mb-1 cursor-pointer group"
    @click="handleClick"
  >
    <div class="flex items-center justify-start px-2 py-1.5 select-none transition-all hover:bg-muted/30 rounded-md">
      <div class="header-content flex items-center gap-1.5 flex-1">
        <span class="type-icon flex items-center justify-center text-indigo-500">
          <component :is="getToolIcon(toolName)" class="w-3.5 h-3.5" />
        </span>
        <span class="header-text text-sm font-medium text-foreground">{{ getToolLabel(toolName, t) }}</span>
        <span class="status-icon flex items-center justify-center" :class="statusIconClass">
          <Check v-if="isCompleted" class="w-3.5 h-3.5" />
          <X v-else-if="isCancelled" class="w-3.5 h-3.5" />
          <Loader2 v-else class="w-3.5 h-3.5 animate-spin" />
        </span>
        <span v-if="isCancelled" class="text-sm text-muted-foreground ml-1">
          {{ cancelledReason }}
        </span>
        <div v-if="!isCancelled" class="expand-icon text-muted-foreground transition-transform duration-200 group-hover:translate-x-1" >
          <ChevronRight class="w-3.5 h-3.5" />
        </div>
        <span class="text-[10px] opacity-70 font-normal text-muted-foreground/60 ml-1.5" v-if="timestamp">{{ formatTime(timestamp) }}</span>
        <span v-if="!isCancelled" class="click-hint text-sm text-muted-foreground ml-1.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100">{{ t('common.viewDetails') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  Check,
  X,
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
  },
  isCancelled: {
    type: Boolean,
    default: false
  },
  cancelledReason: {
    type: String,
    default: '已取消'
  }
})

const emit = defineEmits(['click'])

const { t } = useLanguage()

const toolName = computed(() => props.toolCall.function?.name || '')
const isCompleted = computed(() => !!props.toolResult && !props.isCancelled)

const statusIconClass = computed(() => {
  if (isCompleted.value) return 'text-green-500'
  if (props.isCancelled) return 'text-muted-foreground'
  return 'text-indigo-500'
})

const toolIconMap = {
  file_read: FileText,
  file_write: Save,
  file_update: Edit3,
  view_files: FileText,
  write_to_file: Save,
  download_file_from_url: Download,
  extract_text_from_non_text_file: FileText,
  search_codebase: Search,
  execute_shell_command: Terminal,
  execute_python_code: Code,
  execute_javascript_code: Code,
  run_command: Terminal,
  fetch_webpages: Globe,
  web_search: Globe,
  search_web_page: Globe,
  fetch_webpage: Globe,
  web_fetcher: Globe,
  analyze_image: Image,
  search_image_from_web: Image,
  generate_image: Image,
  remember_user_memory: Database,
  recall_user_memory: Database,
  recall_user_memory_by_type: Database,
  forget_user_memory: Database,
  search_memory: Database,
  todo_write: ListTodo,
  todo_read: ListTodo,
  list_tasks: ListTodo,
  add_task: ListTodo,
  delete_task: ListTodo,
  complete_task: ListTodo,
  send_message_through_im: Mail,
  load_skill: Settings,
  ask_followup_question: Mail,
  questionnaire: ListTodo,
  list_dir: FileText,
  search_by_regex: Search,
  delete_file: FileText,
  rename_file: FileText,
  playwright_navigate: Globe,
  playwright_click: Globe,
  playwright_screenshot: Image,
  playwright_fill: Globe,
  playwright_hover: Globe,
  playwright_evaluate: Code,
  compress_conversation_history: Minimize2,
}

const getToolIcon = (name) => {
  return toolIconMap[name] || Zap
}

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)
  if (!isNaN(num)) {
    dateVal = num < 10000000000 ? num * 1000 : num
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
  }
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

const handleClick = () => {
  emit('click', props.toolCall, props.toolResult)
}
</script>
