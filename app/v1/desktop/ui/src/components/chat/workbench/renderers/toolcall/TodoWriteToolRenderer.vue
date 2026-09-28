<template>
  <div class="todo-write-container h-full overflow-auto p-4">
    <div v-if="todoSummary" class="mb-4 p-3 bg-muted/30 rounded-lg border border-border/50">
      <div class="flex items-center gap-2 text-sm">
        <ListTodo class="w-4 h-4 text-primary" />
        <span>{{ todoSummary }}</span>
      </div>
    </div>
    <div v-if="todoTasks.length > 0" class="space-y-2">
      <div
        v-for="task in todoTasks"
        :key="task.id"
        class="flex items-center gap-3 p-3 rounded-lg border transition-colors"
        :class="getTodoTaskClass(task.status)"
      >
        <div class="flex-shrink-0">
          <CheckCircle2 v-if="task.status === 'completed'" class="w-5 h-5 text-green-500" />
          <Circle v-else-if="task.status === 'pending'" class="w-5 h-5 text-muted-foreground" />
          <Loader2 v-else-if="task.status === 'in_progress'" class="w-5 h-5 text-blue-500 animate-spin" />
          <XCircle v-else-if="task.status === 'failed'" class="w-5 h-5 text-red-500" />
          <HelpCircle v-else class="w-5 h-5 text-muted-foreground" />
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-xs text-muted-foreground font-mono">#{{ task.index }}</span>
            <span class="text-sm font-medium truncate">{{ task.name }}</span>
          </div>
          <div class="text-xs text-muted-foreground/70 mt-0.5">{{ task.id }}</div>
        </div>
        <Badge :variant="getTodoStatusVariant(task.status)" class="text-xs flex-shrink-0">
          {{ getTodoStatusLabel(task.status) }}
        </Badge>
      </div>
    </div>
    <div v-else class="flex items-center justify-center h-32 text-muted-foreground">
      <div class="text-center">
        <ListTodo class="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p class="text-sm">{{ t('workbench.tool.noTasks') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, Circle, Loader2, XCircle, HelpCircle, ListTodo } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'
import { parseToolJsonObjectRecord } from '@/utils/safeParseToolJson.js'

const { t } = useLanguage()

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const todoSummary = computed(() => {
  if (!props.toolResult) return ''
  const o = parseToolJsonObjectRecord(props.toolResult.content)
  return o.summary || ''
})
const todoTasks = computed(() => {
  if (!props.toolResult) return []
  const o = parseToolJsonObjectRecord(props.toolResult.content)
  return Array.isArray(o.tasks) ? o.tasks : []
})
const getTodoTaskClass = (status) => ({
  completed: 'bg-green-500/10 border-green-500/30',
  pending: 'bg-muted/30 border-border/50',
  in_progress: 'bg-blue-500/10 border-blue-500/30',
  failed: 'bg-red-500/10 border-red-500/30'
}[status] || 'bg-muted/30 border-border/50')
const getTodoStatusVariant = (status) => ({
  completed: 'success',
  pending: 'secondary',
  in_progress: 'default',
  failed: 'destructive'
}[status] || 'secondary')
const getTodoStatusLabel = (status) => ({
  completed: t('workbench.tool.statusCompleted'),
  pending: t('workbench.tool.statusPending'),
  in_progress: t('workbench.tool.statusInProgress'),
  failed: t('workbench.tool.statusFailed')
}[status] || status)
</script>
