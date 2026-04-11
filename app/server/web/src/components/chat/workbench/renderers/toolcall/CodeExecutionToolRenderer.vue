<template>
  <div class="ide-container h-full flex flex-col bg-[#1e1e1e] overflow-hidden">
    <div class="code-section flex-[3] min-h-0 overflow-auto">
      <SyntaxHighlighter
        :code="executedCode"
        :language="executionLanguage"
        :show-header="false"
        :show-copy-button="false"
        class="h-full !my-0 !rounded-none !border-0"
      />
    </div>
    <div v-if="executionResult" class="result-section flex-1 min-h-[80px] max-h-[150px] flex flex-col border-t border-border/30 bg-black/20 overflow-hidden">
      <div class="section-header px-3 py-1.5 bg-muted/30 text-[10px] text-muted-foreground flex items-center gap-1.5 flex-none">
        <Terminal class="w-3 h-3" />
        {{ t('workbench.tool.result') }}
      </div>
      <div class="result-content flex-1 overflow-auto px-3 py-2 font-mono text-xs">
        <div v-if="executionError" class="text-red-400">{{ executionError }}</div>
        <pre v-else class="whitespace-pre-wrap text-gray-300">{{ executionResult }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Terminal } from 'lucide-vue-next'
import SyntaxHighlighter from '@/components/chat/SyntaxHighlighter.vue'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null },
  toolName: { type: String, default: '' }
})

const executionLanguage = computed(() => {
  if (props.toolName === 'execute_python_code') return 'python'
  if (props.toolName === 'execute_javascript_code') return 'javascript'
  return 'text'
})

const executedCode = computed(() => props.toolArgs.code || props.toolArgs.script || '')
const executionResult = computed(() => {
  if (!props.toolResult) return ''
  const content = props.toolResult.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.result || parsed.output || parsed.stdout || content
  } catch {
    return content
  }
})
const executionError = computed(() => {
  if (!props.toolResult) return ''
  const content = props.toolResult.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.error || parsed.stderr || ''
  } catch {
    return props.toolResult.is_error ? content : ''
  }
})
</script>
