<template>
  <div 
    class="todo-task-message w-full max-w-[600px] mb-1.5 rounded-lg border bg-card/50 overflow-hidden transition-all hover:border-border/80 cursor-pointer"
    @click="handleClick"
  >
    <!-- Header Section -->
    <div class="flex items-center justify-between px-2.5 py-1.5 border-b bg-muted/20">
      <div class="flex items-center gap-1.5">
        <div class="p-1 rounded bg-primary/10 text-primary">
          <ListTodo class="w-3 h-3" />
        </div>
        <span class="font-medium text-xs">{{ t('chat.todoList') || '任务清单' }}</span>
      </div>
      <!-- Summary Icons -->
      <div v-if="hasSummary" class="flex items-center gap-2 text-[10px] text-muted-foreground">
        <div v-if="addedCount > 0" class="flex items-center gap-0.5 text-green-600">
          <Plus class="w-2.5 h-2.5" />
          <span>{{ addedCount }}</span>
        </div>
        <div v-if="updatedCount > 0" class="flex items-center gap-0.5 text-blue-600">
          <RefreshCw class="w-2.5 h-2.5" />
          <span>{{ updatedCount }}</span>
        </div>
        <div v-if="pendingCount > 0" class="flex items-center gap-0.5 text-orange-600">
          <Circle class="w-2.5 h-2.5" />
          <span>{{ pendingCount }}</span>
        </div>
      </div>
    </div>

    <!-- Content Section -->
    <div class="px-2.5 py-2 space-y-2">
      <!-- Tasks List -->
      <div v-if="tasks.length > 0" class="space-y-1 max-h-[200px] overflow-y-auto pr-0.5">
        <div
          v-for="(task, index) in tasks"
          :key="index"
          class="flex items-start gap-2 px-1.5 py-1 rounded transition-colors hover:bg-muted/40"
          :class="{'opacity-50': task.status === 'completed'}"
        >
          <div class="pt-0.5 flex-shrink-0">
            <div
              class="w-3 h-3 rounded-sm border flex items-center justify-center transition-colors"
              :class="[
                task.status === 'completed'
                  ? 'bg-primary border-primary text-primary-foreground'
                  : task.status === 'in_progress'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-500'
                    : 'border-muted-foreground/40 bg-background'
              ]"
            >
              <Check v-if="task.status === 'completed'" class="w-2 h-2" />
              <Loader2 v-else-if="task.status === 'in_progress'" class="w-2 h-2 animate-spin" />
            </div>
          </div>
          <span
            class="text-xs leading-tight break-words flex-1"
            :class="{
              'line-through text-muted-foreground': task.status === 'completed',
              'text-blue-600 font-medium': task.status === 'in_progress'
            }"
          >
            {{ task.name }}
          </span>
          <span
            v-if="task.status === 'in_progress'"
            class="text-[10px] px-1 py-0 rounded bg-blue-500/15 text-blue-600 flex-shrink-0"
          >
            {{ t('workbench.tool.statusInProgress') || '开始执行' }}
          </span>
        </div>
      </div>
      
      <div v-else class="text-center text-muted-foreground text-xs py-1">
        {{ t('chat.noTasks') || '暂无任务' }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ListTodo, Check, Plus, RefreshCw, Circle, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [Object, String],
    default: null
  },
  isLatest: {
    type: Boolean,
    default: false
  },
  openWorkbench: {
    type: Function,
    default: null
  }
})

const emit = defineEmits(['click'])

const { t } = useLanguage()

const parsedContent = computed(() => {
  if (!props.toolResult) return {}
  
  let content = props.toolResult.content || props.toolResult // 兼容直接传 content 的情况
  
  if (typeof content === 'string') {
    try {
      // 尝试解析 JSON
      if (content.trim().startsWith('{') || content.trim().startsWith('[')) {
        return JSON.parse(content)
      }
    } catch (e) {
      console.warn('Failed to parse todo content:', e)
      return {}
    }
  }
  
  return content || {}
})

const tasks = computed(() => parsedContent.value.tasks || [])

// 解析 summary 信息
const summaryInfo = computed(() => {
  const summary = parsedContent.value.summary || ''
  // 匹配 "新增: X, 更新: Y。当前未完成任务数: Z" 格式
  const match = summary.match(/新增:\s*(\d+).*更新:\s*(\d+).*未完成.*:\s*(\d+)/)
  if (match) {
    return {
      added: parseInt(match[1]) || 0,
      updated: parseInt(match[2]) || 0,
      pending: parseInt(match[3]) || 0
    }
  }
  return null
})

const hasSummary = computed(() => summaryInfo.value !== null)
const addedCount = computed(() => summaryInfo.value?.added || 0)
const updatedCount = computed(() => summaryInfo.value?.updated || 0)
const pendingCount = computed(() => summaryInfo.value?.pending || 0)

const handleClick = () => {
  // 触发点击事件，让父组件打开工作台
  emit('click', props.toolCall, props.toolResult)
}
</script>
