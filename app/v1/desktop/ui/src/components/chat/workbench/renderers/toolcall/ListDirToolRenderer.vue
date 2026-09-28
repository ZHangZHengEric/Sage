<template>
  <div class="h-full flex flex-col">
    <div class="px-4 py-3 border-b border-border flex flex-wrap items-center gap-2 flex-none">
      <FolderTree class="w-4 h-4" />
      <span class="font-mono text-sm break-all">{{ root || '/' }}</span>
      <Badge v-if="depth" variant="outline" class="text-xs">depth: {{ depth }}</Badge>
      <Badge v-if="includeHidden" variant="outline" class="text-xs">+hidden</Badge>
    </div>

    <div class="flex-1 overflow-auto p-4">
      <div v-if="errorMessage" class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive whitespace-pre-wrap">
        {{ errorMessage }}
      </div>
      <pre
        v-else-if="tree"
        class="font-mono text-xs whitespace-pre rounded-lg border border-border/50 bg-muted/20 p-3 overflow-auto"
      >{{ tree }}</pre>
      <div v-else class="text-sm text-muted-foreground italic">Empty directory.</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FolderTree } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null },
})

const depth = computed(() => props.toolArgs.depth)
const includeHidden = computed(() => Boolean(props.toolArgs.include_hidden))

const parsedResult = computed(() => {
  const c = props.toolResult?.content
  if (c == null) return null
  if (typeof c === 'string') {
    try { return JSON.parse(c) } catch { return { tree: c } }
  }
  return c
})

const errorMessage = computed(() => {
  if (props.toolResult?.is_error) {
    const c = props.toolResult.content
    if (typeof c === 'string') return c
    return c?.message || c?.error || JSON.stringify(c)
  }
  const r = parsedResult.value
  if (!r) return ''
  if (r.success === false || r.status === 'error') {
    return r.message || r.error || r.detail || 'list_dir failed'
  }
  return ''
})

const root = computed(() => parsedResult.value?.root || props.toolArgs.path || '')
const tree = computed(() => parsedResult.value?.tree || '')
</script>
