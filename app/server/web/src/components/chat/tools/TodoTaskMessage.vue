<template>
  <div class="todo-task-message w-full max-w-[600px] mb-2 rounded-xl border bg-card/50 overflow-hidden transition-all hover:border-border/80">
    <!-- Header Section -->
    <div class="flex items-center justify-between p-3 border-b bg-muted/20">
      <div class="flex items-center gap-2">
        <div class="p-1.5 rounded-lg bg-primary/10 text-primary">
          <ListTodo class="w-4 h-4" />
        </div>
        <span class="font-medium text-sm">{{ t('chat.todoList') || '任务清单' }}</span>
      </div>
      <button
        v-if="canCollapse"
        type="button"
        class="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60 cursor-pointer shrink-0"
        :title="expanded ? (t('chat.todoListTooltipCollapse') || '仅显示本次修改') : (t('chat.todoListTooltipExpand') || '显示完整清单')"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <ChevronUp v-if="expanded" class="w-4 h-4" />
        <ChevronDown v-else class="w-4 h-4" />
      </button>
    </div>

    <!-- Content Section -->
    <div class="p-4 space-y-4">
      <!-- Summary -->
      <div v-if="summary && showSummary" class="text-sm text-muted-foreground bg-muted/30 p-3 rounded-md">
        {{ summary }}
      </div>

      <!-- Tasks List -->
      <div v-if="visibleTasks.length > 0" class="space-y-2">
        <div
          v-for="(task, index) in visibleTasks"
          :key="task.id || index"
          class="flex items-start gap-3 p-2 rounded-md transition-colors hover:bg-muted/40"
          :class="{'opacity-60': task.status === 'completed'}"
        >
          <div class="pt-0.5 flex-shrink-0">
            <div
              class="w-4 h-4 rounded border flex items-center justify-center transition-colors"
              :class="[
                task.status === 'completed'
                  ? 'bg-primary border-primary text-primary-foreground'
                  : task.status === 'in_progress'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-500'
                    : 'border-muted-foreground/40 bg-background'
              ]"
            >
              <Check v-if="task.status === 'completed'" class="w-3 h-3" />
              <Loader2 v-else-if="task.status === 'in_progress'" class="w-3 h-3 animate-spin" />
            </div>
          </div>
          <span
            class="text-sm leading-tight break-words flex-1"
            :class="{
              'line-through text-muted-foreground': task.status === 'completed',
              'text-blue-600 font-medium': task.status === 'in_progress'
            }"
          >
            {{ task.name }}
          </span>
          <span
            v-if="task.status === 'in_progress'"
            class="text-[11px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-600 flex-shrink-0"
          >
            {{ t('workbench.tool.statusInProgress') || '开始执行' }}
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
import { computed, ref } from 'vue'
import { ListTodo, Check, Loader2, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { parseTodoWriteToolCallArguments } from '@/utils/parseTodoWriteToolArguments.js'

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

const { t } = useLanguage()

const expanded = ref(false)

const parsedToolArgs = computed(() =>
  parseTodoWriteToolCallArguments(props.toolCall?.function?.arguments)
)

const touchedIdsOrdered = computed(() => parsedToolArgs.value.taskIdsOrdered)

const parsedContent = computed(() => {
  if (!props.toolResult) return {}

  let content = props.toolResult.content || props.toolResult

  if (typeof content === 'string') {
    try {
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

const collapsedTasks = computed(() => {
  const full = tasks.value
  if (!touchedIdsOrdered.value.length) return full
  const byId = new Map(full.map((t) => [String(t.id), t]))
  const argList = Array.isArray(parsedToolArgs.value.tasks) ? parsedToolArgs.value.tasks : []
  const out = []
  for (const id of touchedIdsOrdered.value) {
    const row = byId.get(id)
    if (row) {
      out.push(row)
      continue
    }
    const arg = argList.find((x) => x && String(x.id) === id)
    if (arg) {
      out.push({
        id,
        name: arg.content || arg.name || id,
        status: arg.status || 'pending'
      })
    }
  }
  return out.length ? out : full
})

const canCollapse = computed(() => {
  const full = tasks.value
  const sub = collapsedTasks.value
  return sub.length > 0 && full.length > sub.length
})

const visibleTasks = computed(() => {
  if (!canCollapse.value || expanded.value) return tasks.value
  return collapsedTasks.value
})

/** 折叠为「仅本次变更」时隐藏长 summary，展开后与现网一致 */
const showSummary = computed(() => !canCollapse.value || expanded.value)

</script>
