<template>
  <div 
    class="todo-task-message w-full max-w-[600px] mb-2 rounded-xl border bg-card/50 overflow-hidden transition-all hover:border-border/80 cursor-pointer"
    @click="handleClick"
  >
    <!-- Header Section -->
    <div class="flex items-center justify-between p-3 border-b bg-muted/20">
      <div class="flex items-center gap-2">
        <div class="p-1.5 rounded-lg bg-primary/10 text-primary">
          <ListTodo class="w-4 h-4" />
        </div>
        <span class="font-medium text-sm">{{ t('chat.todoList') || '任务清单' }}</span>
      </div>
    </div>

    <!-- Content Section -->
    <div class="p-4 space-y-4">
      <!-- Summary -->
      <div v-if="summary" class="text-sm text-muted-foreground bg-muted/30 p-3 rounded-md">
        {{ summary }}
      </div>

      <!-- Tasks List -->
      <div v-if="tasks.length > 0" class="space-y-2 max-h-[300px] overflow-y-auto pr-1">
        <div 
          v-for="(task, index) in tasks" 
          :key="index" 
          class="flex items-start gap-3 p-2 rounded-md transition-colors hover:bg-muted/40"
          :class="{'opacity-60': task.status === 'completed'}"
        >
          <div class="pt-0.5 flex-shrink-0">
            <div 
              class="w-4 h-4 rounded border flex items-center justify-center transition-colors"
              :class="[
                task.status === 'completed' 
                  ? 'bg-primary border-primary text-primary-foreground' 
                  : 'border-muted-foreground/40 bg-background'
              ]"
            >
              <Check v-if="task.status === 'completed'" class="w-3 h-3" />
            </div>
          </div>
          <span 
            class="text-sm leading-tight break-words"
            :class="{'line-through text-muted-foreground': task.status === 'completed'}"
          >
            {{ task.name }}
          </span>
        </div>
      </div>
      
      <div v-else class="text-center text-muted-foreground text-sm py-2">
        {{ t('chat.noTasks') || '暂无任务' }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ListTodo, Check } from 'lucide-vue-next'
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

const summary = computed(() => parsedContent.value.summary || '')
const tasks = computed(() => parsedContent.value.tasks || [])

const handleClick = () => {
  // 触发点击事件，让父组件打开工作台
  emit('click', props.toolCall, props.toolResult)
}
</script>
