<template>
  <div class="shell-container bg-black text-green-400 font-mono text-sm p-4 h-full overflow-auto">
    <div class="shell-header text-gray-500 mb-2">$ {{ shellCommand }}</div>
    <div v-if="shellOutput" class="shell-output whitespace-pre-wrap break-all">{{ shellOutput }}</div>
    <div v-if="shellError" class="shell-error text-red-400 mt-2 whitespace-pre-wrap break-all">{{ shellError }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const shellCommand = computed(() => props.toolArgs.command || props.toolArgs.cmd || '')

const shellOutput = computed(() => {
  if (!props.toolResult) return ''
  const content = props.toolResult.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.stdout || parsed.output || content
    } catch {
      return content
    }
  }
  return content?.stdout || content?.output || JSON.stringify(content)
})

const shellError = computed(() => {
  if (!props.toolResult) return ''
  const content = props.toolResult.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.stderr || parsed.error || ''
    } catch {
      return ''
    }
  }
  return content?.stderr || content?.error || ''
})
</script>
