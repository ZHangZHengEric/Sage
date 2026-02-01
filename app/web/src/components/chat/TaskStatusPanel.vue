<template>
  <div class="w-[35%] flex flex-col border-l border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 shadow-xl">
    <div class="flex items-center justify-between p-4 border-b border-border">
      <h3 class="text-base font-semibold">{{ t('task.title') }}</h3>
      <Button 
        variant="ghost" 
        size="icon" 
        class="h-8 w-8" 
        @click="$emit('close')"
      >
        <X class="w-4 h-4" />
      </Button>
    </div>
    
    <ScrollArea class="flex-1">
      <div class="p-4 space-y-4">
        <div v-if="hasValidTasks" class="space-y-2">
          <div 
            v-for="(task, index) in taskStatus" 
            :key="task.task_id || index"
            class="rounded-lg border bg-card text-card-foreground shadow-sm"
          >
            <div 
              class="flex items-center gap-3 p-3 cursor-pointer hover:bg-muted/50 transition-colors rounded-t-lg"
              @click="$emit('toggleTask', task.task_id)"
            >
              <Button variant="ghost" size="icon" class="h-6 w-6 shrink-0 text-muted-foreground">
                <ChevronDown v-if="expandedTasks.has(task.task_id)" class="w-4 h-4" />
                <ChevronRight v-else class="w-4 h-4" />
              </Button>
              
              <span class="flex-1 text-sm font-medium truncate">
                {{ task.task_name || `${t('task.taskName')} ${index + 1}` }}
              </span>
              
              <Badge :variant="getStatusVariant(task.status)" class="shrink-0 capitalize">
                <component :is="getStatusIcon(task.status)" class="w-3 h-3 mr-1" />
                {{ task.status }}
              </Badge>
            </div>
            
            <div v-if="expandedTasks.has(task.task_id)" class="px-4 pb-4 pt-0 space-y-3 animate-in slide-in-from-top-2 duration-200">
              <Separator class="mb-3" />
              
              <div v-if="task.description" class="text-sm">
                <span class="font-medium text-muted-foreground">{{ t('task.description') }}: </span>
                <span class="text-foreground">{{ task.description }}</span>
              </div>
              
              <div v-if="task.progress !== undefined" class="space-y-1.5">
                <div class="flex justify-between text-xs">
                  <span class="font-medium text-muted-foreground">{{ t('task.progress') }}</span>
                  <span>{{ task.progress }}%</span>
                </div>
                <div class="h-2 w-full bg-secondary rounded-full overflow-hidden">
                  <div 
                    class="h-full bg-primary transition-all duration-500 ease-in-out" 
                    :style="{ width: `${task.progress}%` }"
                  ></div>
                </div>
              </div>
              
              <div class="grid grid-cols-2 gap-2 text-xs">
                <div v-if="task.start_time">
                  <span class="font-medium text-muted-foreground">{{ t('task.startTime') }}: </span>
                  <span class="font-mono">{{ formatTime(task.start_time) }}</span>
                </div>
                <div v-if="task.end_time">
                  <span class="font-medium text-muted-foreground">{{ t('task.endTime') }}: </span>
                  <span class="font-mono">{{ formatTime(task.end_time) }}</span>
                </div>
              </div>
              
              <div v-if="task.error" class="p-2 rounded bg-destructive/10 text-destructive text-sm border border-destructive/20">
                <span class="font-medium">{{ t('task.error') }}: </span>
                {{ task.error }}
              </div>
              
              <div v-if="task.execution_summary" class="space-y-2 bg-muted/30 p-2 rounded-md border border-muted">
                <div v-if="task.execution_summary.result_summary">
                  <span class="text-xs font-medium text-muted-foreground block mb-1">{{ t('task.result') }}</span>
                  <div class="text-sm text-foreground whitespace-pre-wrap">{{ task.execution_summary.result_summary }}</div>
                </div>
                
                <div v-if="task.execution_summary.result_documents?.length > 0">
                  <span class="text-xs font-medium text-muted-foreground block mb-1">{{ t('task.relatedDocs') }}</span>
                  <ul class="space-y-1">
                    <li 
                      v-for="(doc, docIndex) in task.execution_summary.result_documents" 
                      :key="docIndex"
                      class="text-xs flex items-center gap-1.5 text-foreground/80"
                    >
                      <FileText class="w-3 h-3 text-muted-foreground" />
                      {{ doc }}
                    </li>
                  </ul>
                </div>
              </div>
              
              <div v-if="task.subtasks && task.subtasks.length > 0" class="pt-2">
                <span class="text-xs font-medium text-muted-foreground block mb-2">{{ t('task.subtasks') }}</span>
                <TaskStatusPanel
                  :task-status="task.subtasks"
                  :expanded-tasks="expandedTasks"
                  @toggle-task="$emit('toggleTask', $event)"
                  @close="$emit('close')"
                  class="!w-full !border-l-0 !shadow-none !bg-transparent !p-0"
                />
              </div>
            </div>
          </div>
        </div>
        <div v-else class="flex flex-col items-center justify-center py-12 text-muted-foreground space-y-3">
          <ClipboardList class="w-12 h-12 opacity-20" />
          <p class="text-sm">{{ t('task.noTasks') }}</p>
        </div>
      </div>
    </ScrollArea>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { 
  X, 
  ChevronRight, 
  ChevronDown, 
  CheckCircle2, 
  Loader2, 
  XCircle, 
  Circle,
  FileText,
  ClipboardList
} from 'lucide-vue-next'

// UI Components
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'

const props = defineProps({
  taskStatus: {
    type: Array,
    default: () => []
  },
  expandedTasks: {
    type: Set,
    default: () => new Set()
  }
})

const emit = defineEmits(['close', 'toggleTask'])

const { t } = useLanguage()

const hasValidFiles = computed(() => {
  // 注意：原代码这里写的是 hasValidTasks 但内部判断逻辑似乎没变
  return props.taskStatus && props.taskStatus.length > 0
})
// 修正原代码可能的命名混淆，这里应该是 hasValidTasks
const hasValidTasks = computed(() => {
  return props.taskStatus && props.taskStatus.length > 0
})

const getStatusIcon = (status) => {
  switch (status) {
    case 'completed': return CheckCircle2
    case 'running': return Loader2
    case 'failed': return XCircle
    default: return Circle
  }
}

const getStatusVariant = (status) => {
  switch (status) {
    case 'completed': return 'default' // 绿色/默认
    case 'running': return 'secondary' // 蓝色/次要
    case 'failed': return 'destructive' // 红色/破坏性
    default: return 'outline' // 灰色/轮廓
  }
}

const formatTime = (timeString) => {
  if (!timeString) return ''
  return new Date(timeString).toLocaleString()
}

// 调试：打印任务数据结构
onMounted(() => {
  if (props.taskStatus && props.taskStatus.length > 0) {
    console.log('📋 任务数据结构:', props.taskStatus)
  }
})
</script>