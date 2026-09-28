<template>
  <div class="h-full flex flex-col">
    <div class="px-4 py-3 border-b border-border flex flex-wrap items-center gap-2 flex-none">
      <FolderSearch class="w-4 h-4" />
      <code class="font-mono text-sm bg-muted/40 px-2 py-0.5 rounded break-all">{{ pattern }}</code>
      <Badge v-if="root" variant="outline" class="text-xs font-mono break-all">{{ root }}</Badge>
      <span class="ml-auto text-xs text-muted-foreground">
        <template v-if="errorMessage">—</template>
        <template v-else>{{ files.length }} {{ files.length === 1 ? 'file' : 'files' }}</template>
        <span v-if="truncated" class="ml-1 text-amber-500">(truncated)</span>
      </span>
    </div>

    <div class="flex-1 overflow-auto p-4">
      <div v-if="errorMessage" class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive whitespace-pre-wrap">
        {{ errorMessage }}
      </div>
      <div v-else-if="!files.length" class="text-sm text-muted-foreground italic">No files matched.</div>
      <div v-else class="rounded-lg border border-border/50 overflow-hidden">
        <div
          v-for="(f, i) in files"
          :key="i"
          class="flex items-center gap-2 font-mono text-xs px-3 py-1.5 border-b border-border/30 last:border-b-0 hover:bg-muted/30"
        >
          <FileText class="w-3.5 h-3.5 text-muted-foreground flex-none" />
          <span class="break-all min-w-0">{{ f }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FolderSearch, FileText } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null },
})

const pattern = computed(() => props.toolArgs.pattern || '')

const parsedResult = computed(() => {
  const c = props.toolResult?.content
  if (c == null) return null
  if (typeof c === 'string') {
    try { return JSON.parse(c) } catch { return { raw: c } }
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
    return r.message || r.error || r.detail || 'glob failed'
  }
  return ''
})

const root = computed(() => parsedResult.value?.root || props.toolArgs.path || '')
const files = computed(() => Array.isArray(parsedResult.value?.files) ? parsedResult.value.files : [])
const truncated = computed(() => Boolean(parsedResult.value?.truncated))
</script>
