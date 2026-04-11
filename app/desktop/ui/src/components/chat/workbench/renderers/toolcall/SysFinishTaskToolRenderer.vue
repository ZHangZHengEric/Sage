<template>
  <div class="sys-finish-task-container h-full flex flex-col">
    <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
      <Loader2 class="w-5 h-5 animate-spin mr-2" />
      <span>{{ t('workbench.tool.finishingTask') }}</span>
    </div>
    <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
      <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div>
        <p class="font-medium">{{ t('workbench.tool.finishFailed') }}</p>
        <p class="text-sm opacity-80 mt-1">{{ finishTaskError }}</p>
      </div>
    </div>
    <div v-else class="flex flex-col h-full overflow-hidden">
      <div class="flex items-center gap-3 p-4 border-b border-border/30 bg-green-500/5 flex-shrink-0">
        <div class="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center">
          <CheckCircle class="w-5 h-5 text-green-600" />
        </div>
        <div>
          <p class="font-medium text-sm">{{ t('workbench.tool.taskCompleted') }}</p>
          <p class="text-xs text-muted-foreground">{{ finishTaskStatus }}</p>
        </div>
      </div>
      <div class="flex-1 overflow-hidden">
        <div class="h-full overflow-auto custom-scrollbar p-4">
          <MarkdownRenderer :content="finishTaskResult" class="text-sm" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Loader2, XCircle, CheckCircle } from 'lucide-vue-next'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const finishTaskStatus = computed(() => props.toolArgs.status || 'success')
const finishTaskResult = computed(() => {
  const resultFromArgs = props.toolArgs.result
  if (resultFromArgs) return typeof resultFromArgs === 'string' ? resultFromArgs : JSON.stringify(resultFromArgs, null, 2)
  if (!props.toolResult) return ''
  return typeof props.toolResult.content === 'string' ? props.toolResult.content : JSON.stringify(props.toolResult.content, null, 2)
})
const finishTaskError = computed(() => {
  if (!props.toolResult?.is_error) return ''
  return typeof props.toolResult.content === 'string' ? props.toolResult.content : JSON.stringify(props.toolResult.content)
})
</script>
