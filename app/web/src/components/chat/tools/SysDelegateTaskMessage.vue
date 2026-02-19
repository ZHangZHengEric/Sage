<template>
  <div class="sys-delegate-task-message w-full max-w-[600px] mb-2 rounded-xl border bg-card/50 overflow-hidden transition-all hover:border-border/80">
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
    <div class="p-4 space-y-4">
      <div v-for="(task, index) in tasks" :key="index" class="space-y-3">
        <!-- Agent Info -->
        <div class="grid grid-cols-[100px_1fr] gap-2 text-sm">
          <div class="text-muted-foreground font-medium flex items-center gap-1">
            <User class="w-3.5 h-3.5" />
            {{ t('chat.targetAgent') }}
          </div>
          <div class="font-semibold">{{ task.agent_id || '-' }}</div>
          
          <div class="text-muted-foreground font-medium flex items-center gap-1">
            <Info class="w-3.5 h-3.5" />
            {{ t('chat.taskContent') }}
          </div>
          <div class="text-foreground/80 leading-relaxed whitespace-pre-wrap">{{ task.content || '-' }}</div>
        </div>

        <!-- Session ID / Action Button -->
        <div v-if="task.session_id" class="flex justify-end pt-2">
          <Button 
            variant="outline" 
            size="sm" 
            class="gap-2 text-xs h-8"
            @click.stop="openSubSession(task.session_id)"
          >
            <MessageSquare class="w-3.5 h-3.5" />
            {{ t('chat.viewSubSession') }}
          </Button>
        </div>
      </div>
  
      <!-- Error Message -->
      <div v-if="isError && errorMessage" class="text-destructive text-sm bg-destructive/5 p-3 rounded-md">
        {{ errorMessage }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Share2, User, Info, Check, Loader2, AlertCircle, MessageSquare } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { Button } from '@/components/ui/button'

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
  }
})

const emit = defineEmits(['openSubSession'])
const { t } = useLanguage()

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

const openSubSession = (sessionId) => {
  emit('openSubSession', sessionId)
}
</script>
