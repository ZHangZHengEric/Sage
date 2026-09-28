<template>
  <div class="compress-history-container h-full flex flex-col overflow-hidden">
    <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
      <Loader2 class="w-5 h-5 animate-spin mr-2" />
      <span>{{ t('workbench.tool.compressingHistory') }}</span>
    </div>
    <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
      <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div>
        <p class="font-medium">{{ t('workbench.tool.compressFailed') }}</p>
        <p class="text-sm opacity-80 mt-1">{{ compressHistoryError }}</p>
      </div>
    </div>
    <div v-else class="flex flex-col h-full overflow-hidden">
      <div class="flex items-center gap-3 p-4 border-b border-border/30 bg-blue-500/5 flex-shrink-0">
        <div class="w-10 h-10 rounded-full bg-blue-500/20 flex items-center justify-center">
          <Minimize2 class="w-5 h-5 text-blue-600" />
        </div>
        <div>
          <p class="font-medium text-sm">{{ t('workbench.tool.historyCompressed') }}</p>
          <p class="text-xs text-muted-foreground">{{ compressHistoryStats }}</p>
        </div>
      </div>
      <div class="flex-1 overflow-hidden">
        <div class="h-full overflow-auto custom-scrollbar p-4">
          <MarkdownRenderer :content="compressHistoryResult" class="text-sm" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Loader2, XCircle, Minimize2 } from 'lucide-vue-next'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const compressHistoryResult = computed(() => {
  if (!props.toolResult) return ''
  const content = props.toolResult.content
  if (typeof content === 'string') return content
  try {
    const parsed = JSON.parse(content)
    return parsed.message || parsed.content || content
  } catch {
    return content
  }
})
const compressHistoryStats = computed(() => {
  const result = compressHistoryResult.value
  if (!result) return ''
  const match = result.match(/(\d+)\s*tokens?\s*→\s*(\d+)\s*tokens?.*\((压缩率|compression):\s*([^)]+)\)/i)
  if (match) return `${match[1]} → ${match[2]} tokens (${match[4]})`
  return ''
})
const compressHistoryError = computed(() => {
  if (!props.toolResult?.content) return ''
  const content = props.toolResult.content
  if (typeof content === 'string') return content
  try {
    const parsed = JSON.parse(content)
    return parsed.message || parsed.error || t('workbench.tool.unknownError')
  } catch {
    return String(content)
  }
})
</script>
