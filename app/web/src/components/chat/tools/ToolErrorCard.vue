<template>
  <div class="p-4 border border-destructive/20 bg-destructive/5 rounded-lg text-destructive">
    <div class="font-semibold mb-2 flex items-center gap-2">
      <span class="i-lucide-alert-circle"></span>
      Tool Execution Error
    </div>
    <pre class="text-xs overflow-auto whitespace-pre-wrap">{{ errorMessage }}</pre>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  toolResult: {
    type: [Object, String],
    default: null
  }
})

const errorMessage = computed(() => {
  if (typeof props.toolResult === 'string') return props.toolResult
  return props.toolResult?.message || props.toolResult?.error || JSON.stringify(props.toolResult)
})
</script>
