<template>
  <div 
    class="sys-delegate-task-message w-full max-w-[600px] mb-2 rounded-xl border bg-card/50 overflow-hidden transition-all hover:border-border/80 cursor-pointer"
    @click="handleClick"
  >
    <!-- Header Section -->
    <div class="flex items-center justify-between p-3 border-b bg-muted/20">
      <div class="flex items-center gap-2">
        <div class="p-1.5 rounded-lg bg-primary/10 text-primary">
          <Share2 class="w-4 h-4" />
        </div>
        <span class="font-medium text-sm">{{ t('chat.taskDelegation') }}</span>
      </div>
      
      <!-- Status Indicator -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
          :class="[
            isError ? 'bg-destructive/10 text-destructive' : 
            isCompleted ? 'bg-green-500/10 text-green-600' : 
            'bg-blue-500/10 text-blue-600'
          ]">
          <AlertCircle v-if="isError" class="w-3 h-3" />
          <Check v-else-if="isCompleted" class="w-3 h-3" />
          <Loader2 v-else class="w-3 h-3 animate-spin" />
          <span>{{ statusText }}</span>
        </div>
      </div>
    </div>

    <!-- Content Section -->
    <div class="p-4 space-y-3">
      <!-- Single Task Display -->
      <div v-if="tasks.length === 1" class="space-y-3">
        <!-- Agent Delegation Visual -->
        <div class="flex items-center justify-center gap-3 py-2 min-w-0">
          <!-- Source Agent (Current) - flex-shrink-0 prevents compression -->
          <div class="flex flex-col items-center gap-2 flex-shrink-0">
            <div class="relative">
              <img 
                :src="currentAgentAvatar" 
                :alt="currentAgentName"
                class="w-12 h-12 rounded-xl bg-muted object-cover border-2 border-primary/20 flex-shrink-0"
              />
              <div class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                <User class="w-3 h-3 text-primary-foreground" />
              </div>
            </div>
            <span class="text-xs text-muted-foreground font-medium whitespace-nowrap">{{ currentAgentName }}</span>
          </div>

          <!-- Delegation Arrow with Task Name - min-w-0 allows compression -->
          <div class="flex flex-col items-center gap-1 min-w-0 flex-1 px-2">
            <div class="flex items-center gap-1 text-muted-foreground flex-shrink-0">
              <ArrowRight class="w-5 h-5" />
            </div>
            <span class="text-xs font-medium text-foreground text-center truncate w-full">{{ tasks[0].task_name || tasks[0].original_task || t('chat.task') }}</span>
            <Button 
              variant="ghost" 
              size="sm" 
              class="h-6 text-xs gap-1 mt-1 flex-shrink-0"
              @click="openTaskDetail(0)"
            >
              <Eye class="w-3.5 h-3.5" />
              {{ t('chat.viewDetail') }}
            </Button>
          </div>

          <!-- Target Agent - flex-shrink-0 prevents compression -->
          <div class="flex flex-col items-center gap-2 flex-shrink-0">
            <div class="relative">
              <img 
                :src="getTargetAgentAvatar(tasks[0].agent_id)" 
                :alt="tasks[0].agent_id"
                class="w-12 h-12 rounded-xl bg-muted object-cover border-2 flex-shrink-0"
                :class="isCompleted ? 'border-green-500/50' : 'border-blue-500/50'"
              />
              <!-- Busy Indicator -->
              <div v-if="!isCompleted && !isError" class="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center animate-pulse">
                <Loader2 class="w-3 h-3 text-white animate-spin" />
              </div>
              <!-- Completed Indicator -->
              <div v-else-if="isCompleted" class="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-green-500 flex items-center justify-center">
                <Check class="w-3 h-3 text-white" />
              </div>
              <!-- Error Indicator -->
              <div v-else-if="isError" class="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-destructive flex items-center justify-center">
                <X class="w-3 h-3 text-white" />
              </div>
            </div>
            <span class="text-xs text-muted-foreground font-medium truncate max-w-[100px]">{{ getTargetAgentName(tasks[0].agent_id) }}</span>
          </div>
        </div>

        <!-- Result Section (when completed) -->
        <div v-if="isCompleted && taskResult" class="bg-green-500/5 rounded-lg p-3 space-y-2 border border-green-500/20">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <CheckCircle class="w-4 h-4 text-green-600" />
              <span class="text-sm font-medium text-green-700">{{ t('chat.taskCompleted') }}</span>
            </div>
            <Button 
              variant="ghost" 
              size="sm" 
              class="h-6 text-xs gap-1"
              @click="toggleResult(0)"
            >
              <Eye v-if="!showResult[0]" class="w-3.5 h-3.5" />
              <EyeOff v-else class="w-3.5 h-3.5" />
              {{ showResult[0] ? t('chat.hideResult') : t('chat.viewResult') }}
            </Button>
          </div>
          
          <!-- Expandable Result -->
          <div v-if="showResult[0]" class="pt-2 border-t border-green-500/20">
            <div class="max-h-[300px] overflow-y-auto custom-scrollbar bg-background rounded p-2">
              <MarkdownRenderer :content="taskResult" class="text-xs" />
            </div>
          </div>
        </div>

        <!-- Session ID / Action Button -->
        <div v-if="tasks[0].session_id" class="flex justify-end pt-2">
          <Button 
            variant="outline" 
            size="sm" 
            class="gap-2 text-xs h-8"
            @click.stop="openSubSession(tasks[0].session_id)"
          >
            <MessageSquare class="w-3.5 h-3.5" />
            {{ t('chat.viewSubSession') }}
          </Button>
        </div>
      </div>

      <!-- Multiple Tasks Display -->
      <div v-else class="space-y-3">
        <!-- Summary -->
        <div class="flex items-center justify-between">
          <span class="text-sm text-muted-foreground">{{ t('chat.multipleTasks', { count: tasks.length }) }}</span>
          <Button 
            variant="outline" 
            size="sm" 
            class="h-7 text-xs gap-1"
            @click="showTaskListDialog = true"
          >
            <List class="w-3.5 h-3.5" />
            {{ t('chat.viewAllTasks') }}
          </Button>
        </div>

        <!-- Quick Preview of First Task -->
        <div class="flex items-center justify-center gap-4 py-2">
          <!-- Source Agent (Current) -->
          <div class="flex flex-col items-center gap-2">
            <div class="relative">
              <img 
                :src="currentAgentAvatar" 
                :alt="currentAgentName"
                class="w-12 h-12 rounded-xl bg-muted object-cover border-2 border-primary/20"
              />
              <div class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                <User class="w-3 h-3 text-primary-foreground" />
              </div>
            </div>
            <span class="text-xs text-muted-foreground font-medium">{{ currentAgentName }}</span>
          </div>

          <!-- Delegation Arrow with Task Count -->
          <div class="flex flex-col items-center gap-1 flex-1">
            <div class="flex items-center gap-1 text-muted-foreground">
              <ArrowRight class="w-5 h-5" />
            </div>
            <span class="text-xs font-medium text-foreground">{{ tasks.length }} {{ t('chat.tasks') }}</span>
            <Button 
              variant="ghost" 
              size="sm" 
              class="h-6 text-xs gap-1 mt-1"
              @click="showTaskListDialog = true"
            >
              <Eye class="w-3.5 h-3.5" />
              {{ t('chat.viewDetail') }}
            </Button>
          </div>

          <!-- Target Agents Preview -->
          <div class="flex flex-col items-center gap-2">
            <div class="flex -space-x-2">
              <img 
                v-for="(task, idx) in tasks.slice(0, 3)" 
                :key="idx"
                :src="getTargetAgentAvatar(task.agent_id)" 
                :alt="task.agent_id"
                class="w-10 h-10 rounded-xl bg-muted object-cover border-2 border-background"
                :class="isCompleted ? 'border-green-500/50' : 'border-blue-500/50'"
              />
              <div v-if="tasks.length > 3" class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center border-2 border-background text-xs font-medium">
                +{{ tasks.length - 3 }}
              </div>
            </div>
            <span class="text-xs text-muted-foreground font-medium">{{ tasks.length }} {{ t('chat.agents') }}</span>
          </div>
        </div>

        <!-- Result Section (when completed) -->
        <div v-if="isCompleted && taskResult" class="bg-green-500/5 rounded-lg p-3 space-y-2 border border-green-500/20">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <CheckCircle class="w-4 h-4 text-green-600" />
              <span class="text-sm font-medium text-green-700">{{ t('chat.allTasksCompleted') }}</span>
            </div>
            <Button 
              variant="ghost" 
              size="sm" 
              class="h-6 text-xs gap-1"
              @click="toggleResult(0)"
            >
              <Eye v-if="!showResult[0]" class="w-3.5 h-3.5" />
              <EyeOff v-else class="w-3.5 h-3.5" />
              {{ showResult[0] ? t('chat.hideResult') : t('chat.viewResult') }}
            </Button>
          </div>
          
          <!-- Expandable Result -->
          <div v-if="showResult[0]" class="pt-2 border-t border-green-500/20">
            <div class="max-h-[300px] overflow-y-auto custom-scrollbar bg-background rounded p-2">
              <MarkdownRenderer :content="taskResult" class="text-xs" />
            </div>
          </div>
        </div>
      </div>
  
      <!-- Error Message -->
      <div v-if="isError && errorMessage" class="text-destructive text-sm bg-destructive/5 p-3 rounded-md">
        {{ errorMessage }}
      </div>
    </div>

    <!-- Task Detail Dialog -->
    <Dialog v-model:open="showTaskDetailDialog">
      <DialogContent class="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{{ t('chat.taskDetail') }}</DialogTitle>
          <DialogDescription>{{ selectedTask?.task_name || selectedTask?.original_task }}</DialogDescription>
        </DialogHeader>
        
        <div class="flex-1 overflow-y-auto py-4 space-y-4">
          <!-- Agent Delegation Info -->
          <div class="flex items-center justify-center gap-6 py-4 bg-muted/30 rounded-lg">
            <!-- Source Agent -->
            <div class="flex flex-col items-center gap-2">
              <img 
                :src="currentAgentAvatar" 
                :alt="currentAgentName"
                class="w-14 h-14 rounded-xl bg-muted object-cover border-2 border-primary/20"
              />
              <span class="text-sm font-medium">{{ currentAgentName }}</span>
              <span class="text-xs text-muted-foreground">{{ t('chat.delegator') }}</span>
            </div>

            <ArrowRight class="w-6 h-6 text-muted-foreground" />

            <!-- Target Agent -->
            <div class="flex flex-col items-center gap-2">
              <img 
                :src="getTargetAgentAvatar(selectedTask?.agent_id)" 
                :alt="selectedTask?.agent_id"
                class="w-14 h-14 rounded-xl bg-muted object-cover border-2 border-primary/20"
              />
              <span class="text-sm font-medium">{{ getTargetAgentName(selectedTask?.agent_id) }}</span>
              <span class="text-xs text-muted-foreground">{{ t('chat.executor') }}</span>
            </div>
          </div>

          <!-- Task Content -->
          <div class="space-y-2">
            <h4 class="text-sm font-medium">{{ t('chat.taskContent') }}</h4>
            <div class="bg-muted/30 rounded-lg p-3 max-h-[300px] overflow-y-auto custom-scrollbar">
              <pre class="text-xs whitespace-pre-wrap font-mono">{{ selectedTask?.content || '-' }}</pre>
            </div>
          </div>

          <!-- Session Info -->
          <div v-if="selectedTask?.session_id" class="flex items-center justify-between pt-2">
            <span class="text-xs text-muted-foreground">Session: {{ selectedTask.session_id }}</span>
            <Button 
              variant="outline" 
              size="sm" 
              class="gap-2 text-xs"
              @click="openSubSession(selectedTask.session_id); showTaskDetailDialog = false"
            >
              <MessageSquare class="w-3.5 h-3.5" />
              {{ t('chat.viewSubSession') }}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- Task List Dialog (for multiple tasks) -->
    <Dialog v-model:open="showTaskListDialog">
      <DialogContent class="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{{ t('chat.taskList') }}</DialogTitle>
          <DialogDescription>{{ t('chat.taskListDescription', { count: tasks.length }) }}</DialogDescription>
        </DialogHeader>
        
        <div class="flex-1 overflow-y-auto py-4 space-y-3">
          <div 
            v-for="(task, index) in tasks" 
            :key="index"
            class="p-3 border rounded-lg hover:bg-muted/30 transition-colors cursor-pointer"
            @click="openTaskDetailFromList(index)"
          >
            <div class="flex items-center gap-3">
              <img 
                :src="getTargetAgentAvatar(task.agent_id)" 
                :alt="task.agent_id"
                class="w-10 h-10 rounded-lg bg-muted object-cover"
              />
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium truncate">{{ task.task_name || task.original_task || t('chat.untitledTask') }}</p>
                <p class="text-xs text-muted-foreground truncate">{{ getTargetAgentName(task.agent_id) }}</p>
              </div>
              <Button variant="ghost" size="sm" class="h-7 text-xs">
                <Eye class="w-3.5 h-3.5 mr-1" />
                {{ t('chat.view') }}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Share2, User, Check, Loader2, AlertCircle, MessageSquare, ArrowRight, Eye, EyeOff, CheckCircle, X, List } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import MarkdownRenderer from '../MarkdownRenderer.vue'

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
  currentAgent: {
    type: Object,
    default: null
  },
  openWorkbench: {
    type: Function,
    default: null
  }
})

const emit = defineEmits(['openSubSession', 'click'])
const { t } = useLanguage()

// Dialog states
const showTaskDetailDialog = ref(false)
const showTaskListDialog = ref(false)
const selectedTaskIndex = ref(0)

// Toggle states
const showResult = ref({})

const toggleResult = (index) => {
  showResult.value[index] = !showResult.value[index]
}

const openTaskDetail = (index) => {
  selectedTaskIndex.value = index
  showTaskDetailDialog.value = true
}

const openTaskDetailFromList = (index) => {
  showTaskListDialog.value = false
  selectedTaskIndex.value = index
  showTaskDetailDialog.value = true
}

const args = computed(() => {
  try {
    if (typeof props.toolCall.function.arguments === 'string') {
      return JSON.parse(props.toolCall.function.arguments)
    }
    return props.toolCall.function.arguments
  } catch (e) {
    console.error('Failed to parse arguments:', e)
    return {}
  }
})

const tasks = computed(() => {
  return args.value.tasks || []
})

const selectedTask = computed(() => {
  return tasks.value[selectedTaskIndex.value] || null
})

// Current Agent Info
const currentAgentName = computed(() => {
  return props.currentAgent?.name || t('chat.currentAgent')
})

// Generate avatar URL - consistent with MessageAvatar.vue
const generateAvatarUrl = (agentId) => {
  if (!agentId) return ''
  return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}`
}

const currentAgentAvatar = computed(() => {
  if (props.currentAgent?.avatar_url) {
    return props.currentAgent.avatar_url
  }
  // Use agent id or name as seed for consistent avatar
  const seed = props.currentAgent?.id || props.currentAgent?.name || 'current'
  return generateAvatarUrl(seed)
})

// Target Agent Info
const getTargetAgentAvatar = (agentId) => {
  return generateAvatarUrl(agentId)
}

const getTargetAgentName = (agentId) => {
  // Try to extract name from agent_id, or use shortened version
  if (!agentId) return t('chat.unknownAgent')
  return agentId.length > 15 ? agentId.slice(0, 12) + '...' : agentId
}

const isError = computed(() => {
  if (props.toolResult?.status === 'error' || props.toolResult?.is_error) return true
  return false
})

const isCompleted = computed(() => {
  return !!props.toolResult && !isError.value
})

const errorMessage = computed(() => {
  if (isError.value) {
    return props.toolResult?.content || props.toolResult?.message || t('error.unknown')
  }
  return ''
})

const statusText = computed(() => {
  if (isError.value) return t('status.failed')
  if (isCompleted.value) return t('status.completed')
  return t('status.inProgress')
})

const taskResult = computed(() => {
  if (!props.toolResult) return null
  if (typeof props.toolResult === 'string') {
    return props.toolResult
  }
  return props.toolResult.content || props.toolResult.message || JSON.stringify(props.toolResult, null, 2)
})

const openSubSession = (sessionId) => {
  emit('openSubSession', sessionId)
}

const handleClick = () => {
  // 触发点击事件，让父组件打开工作台
  emit('click', props.toolCall, props.toolResult)
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.3);
  border-radius: 2px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.5);
}
</style>
