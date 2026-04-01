<template>
  <div class="h-full flex flex-col">
    <div class="file-header px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
      <FileText class="w-4 h-4" />
      <span class="font-medium text-sm">{{ fileUpdatePath }}</span>
      <Badge variant="secondary" class="text-xs">{{ fileUpdateModeLabel }}</Badge>
      <Badge v-if="fileUpdateOperations.length" variant="outline" class="text-xs">
        {{ fileUpdateOperations.length }} {{ t('workbench.tool.fileUpdate.operations') }}
      </Badge>
    </div>
    <div class="flex-1 overflow-auto p-4 space-y-4">
      <div class="grid grid-cols-3 gap-3">
        <div class="rounded-lg border border-border/50 bg-muted/20 p-3">
          <div class="text-xs text-muted-foreground mb-1">{{ t('workbench.tool.statusCompleted') }}</div>
          <div class="text-sm font-medium">{{ fileUpdateResultMessage }}</div>
        </div>
        <div class="rounded-lg border border-border/50 bg-muted/20 p-3">
          <div class="text-xs text-muted-foreground mb-1">{{ t('workbench.tool.fileUpdate.replacements') }}</div>
          <div class="text-sm font-medium">{{ fileUpdateReplacements }}</div>
        </div>
        <div class="rounded-lg border border-border/50 bg-muted/20 p-3">
          <div class="text-xs text-muted-foreground mb-1">{{ t('workbench.tool.fileUpdate.operations') }}</div>
          <div class="text-sm font-medium">{{ fileUpdateOperations.length || 1 }}</div>
        </div>
      </div>

      <div v-if="fileUpdateOperations.length" class="space-y-2">
        <div class="text-xs text-muted-foreground">{{ t('workbench.tool.fileUpdate.operations') }}</div>
        <div
          v-for="(operation, index) in fileUpdateOperations"
          :key="`file-update-op-${index}`"
          class="rounded-lg border border-border/50 bg-background p-3"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="text-sm font-medium">{{ fileUpdateOperationTitle(operation, index) }}</div>
            <Badge variant="outline" class="text-xs">{{ fileUpdateOperationModeLabel(operation) }}</Badge>
          </div>
          <div class="mt-2 text-xs text-muted-foreground break-all">
            {{ fileUpdateOperationDetail(operation) }}
          </div>
        </div>
      </div>

      <div v-if="hasArguments" class="space-y-2">
        <div class="text-xs text-muted-foreground flex items-center gap-1">
          <Settings class="w-3 h-3" />
          {{ t('workbench.tool.arguments') }}
        </div>
        <pre class="bg-muted p-3 rounded text-xs whitespace-pre-wrap break-all">{{ formattedArguments }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FileText, Settings } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()

const props = defineProps({
  toolArgs: {
    type: Object,
    default: () => ({})
  },
  toolResult: {
    type: Object,
    default: null
  },
  formattedArguments: {
    type: String,
    default: ''
  },
  displayToolName: {
    type: String,
    default: ''
  },
  hasArguments: {
    type: Boolean,
    default: false
  }
})

const fileUpdateResultData = computed(() => {
  const content = props.toolResult?.content
  if (!content) return null
  try {
    return typeof content === 'string' ? JSON.parse(content) : content
  } catch {
    return null
  }
})
const fileUpdatePath = computed(() => fileUpdateResultData.value?.file_path || props.toolArgs.file_path || '')
const fileUpdateOperations = computed(() => fileUpdateResultData.value?.operations || props.toolArgs.operations || [])
const fileUpdateReplacements = computed(() => fileUpdateResultData.value?.replacements ?? 0)
const fileUpdateResultMessage = computed(() => fileUpdateResultData.value?.message || props.displayToolName)
const fileUpdateModeLabel = computed(() => {
  const mode = fileUpdateResultData.value?.update_mode
  if (mode === 'line_range') return t('workbench.tool.fileUpdate.mode.lineRange')
  if (mode === 'search_replace') return t('workbench.tool.fileUpdate.mode.searchReplace')
  if (mode === 'batch') return t('workbench.tool.fileUpdate.mode.batch')
  return props.displayToolName
})
const fileUpdateOperationModeLabel = (operation) => {
  if (operation?.update_mode === 'line_range' || operation?.start_line !== undefined || operation?.end_line !== undefined) {
    return t('workbench.tool.fileUpdate.mode.lineRange')
  }
  if (operation?.match_mode === 'regex') {
    return t('workbench.tool.fileUpdate.match.regex')
  }
  return t('workbench.tool.fileUpdate.match.text')
}
const fileUpdateOperationTitle = (operation, index) => {
  if (operation?.update_mode === 'line_range' || operation?.start_line !== undefined || operation?.end_line !== undefined) {
    const start = typeof operation?.start_line === 'number' ? operation.start_line + 1 : '?'
    const end = typeof operation?.end_line === 'number' ? operation.end_line : '?'
    return `${t('workbench.tool.fileUpdate.range')} L${start}-L${end}`
  }
  return `${t('workbench.tool.fileUpdate.operations')} ${index + 1}`
}
const fileUpdateOperationDetail = (operation) => {
  if (operation?.update_mode === 'line_range' || operation?.start_line !== undefined || operation?.end_line !== undefined) {
    const linesReplaced = operation?.lines_replaced ?? '-'
    return `${t('workbench.tool.fileUpdate.replacements')}: ${linesReplaced}`
  }
  return operation?.search_pattern || ''
}
</script>
