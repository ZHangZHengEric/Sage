<template>
  <div class="h-full flex flex-col">
    <div class="px-4 py-3 border-b border-border flex flex-wrap items-center gap-2 flex-none">
      <Search class="w-4 h-4" />
      <code class="font-mono text-sm bg-muted/40 px-2 py-0.5 rounded break-all">{{ pattern }}</code>
      <Badge v-if="path" variant="outline" class="text-xs font-mono">{{ path }}</Badge>
      <Badge v-if="globFilter" variant="outline" class="text-xs font-mono">glob: {{ globFilter }}</Badge>
      <Badge v-if="typeFilter" variant="outline" class="text-xs font-mono">type: {{ typeFilter }}</Badge>
      <Badge variant="secondary" class="text-xs">{{ outputMode }}</Badge>
      <Badge v-if="caseInsensitive" variant="outline" class="text-xs">i</Badge>
      <Badge v-if="multiline" variant="outline" class="text-xs">multiline</Badge>
      <span class="ml-auto text-xs text-muted-foreground">
        <template v-if="errorMessage">—</template>
        <template v-else-if="outputMode === 'count'">{{ countTotal }} matches in {{ countList.length }} files</template>
        <template v-else>{{ resultCount }} {{ resultCount === 1 ? 'result' : 'results' }}</template>
        <span v-if="truncated" class="ml-1 text-amber-500">(truncated)</span>
      </span>
    </div>

    <div class="flex-1 overflow-auto p-4 space-y-3">
      <div v-if="errorMessage" class="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive whitespace-pre-wrap">
        {{ errorMessage }}
      </div>

      <template v-else>
        <div v-if="note" class="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-700">
          {{ note }}
        </div>

        <!-- content mode: list of matches -->
        <div v-if="outputMode === 'content'" class="space-y-3">
          <div v-if="!matches.length" class="text-sm text-muted-foreground italic">No matches.</div>
          <div
            v-for="(group, gi) in groupedMatches"
            :key="gi"
            class="rounded-lg border border-border/50 overflow-hidden"
          >
            <div class="bg-muted/40 px-3 py-1.5 border-b border-border/40 flex items-center gap-2">
              <FileText class="w-3.5 h-3.5 text-muted-foreground flex-none" />
              <span class="font-mono text-xs break-all">{{ group.file }}</span>
              <Badge variant="outline" class="text-xs ml-auto">{{ group.items.length }}</Badge>
            </div>
            <div class="font-mono text-xs">
              <div
                v-for="(m, mi) in group.items"
                :key="mi"
                class="flex border-b border-border/30 last:border-b-0 hover:bg-muted/30"
              >
                <div class="flex-none w-16 select-none border-r border-border/40 bg-muted/20 px-2 py-1 text-right text-muted-foreground">
                  {{ m.line }}<span v-if="m.col" class="text-muted-foreground/70">:{{ m.col }}</span>
                </div>
                <pre class="min-w-0 flex-1 whitespace-pre-wrap break-all px-3 py-1">{{ m.line_text || m.match }}</pre>
              </div>
            </div>
          </div>
        </div>

        <!-- files_with_matches mode -->
        <div v-else-if="outputMode === 'files_with_matches'" class="rounded-lg border border-border/50 overflow-hidden">
          <div v-if="!files.length" class="px-3 py-2 text-sm text-muted-foreground italic">No matches.</div>
          <div
            v-for="(f, i) in files"
            :key="i"
            class="font-mono text-xs px-3 py-1.5 border-b border-border/30 last:border-b-0 break-all"
          >
            {{ f }}
          </div>
        </div>

        <!-- count mode -->
        <div v-else-if="outputMode === 'count'" class="rounded-lg border border-border/50 overflow-hidden">
          <div v-if="!countList.length" class="px-3 py-2 text-sm text-muted-foreground italic">No matches.</div>
          <div
            v-for="(c, i) in countList"
            :key="i"
            class="flex items-center justify-between font-mono text-xs px-3 py-1.5 border-b border-border/30 last:border-b-0"
          >
            <span class="break-all min-w-0">{{ c.file }}</span>
            <Badge variant="secondary" class="text-xs ml-2 flex-none">{{ c.matches }}</Badge>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Search, FileText } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null },
})

const pattern = computed(() => props.toolArgs.pattern || '')
const path = computed(() => props.toolArgs.path || '')
const globFilter = computed(() => props.toolArgs.glob || '')
const typeFilter = computed(() => props.toolArgs.type || '')
const outputMode = computed(() => props.toolArgs.output_mode || 'content')
const caseInsensitive = computed(() => Boolean(props.toolArgs.case_insensitive))
const multiline = computed(() => Boolean(props.toolArgs.multiline))

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
    return r.message || r.error || r.detail || 'grep failed'
  }
  return ''
})

const matches = computed(() => Array.isArray(parsedResult.value?.matches) ? parsedResult.value.matches : [])
const files = computed(() => Array.isArray(parsedResult.value?.files) ? parsedResult.value.files : [])
const countList = computed(() => Array.isArray(parsedResult.value?.counts) ? parsedResult.value.counts : [])
const countTotal = computed(() => parsedResult.value?.total ?? 0)
const resultCount = computed(() => parsedResult.value?.count ?? matches.value.length ?? files.value.length ?? 0)
const truncated = computed(() => Boolean(parsedResult.value?.truncated))
const note = computed(() => parsedResult.value?.note || '')

const groupedMatches = computed(() => {
  const map = new Map()
  for (const m of matches.value) {
    const key = m.file || ''
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(m)
  }
  return Array.from(map.entries()).map(([file, items]) => ({ file, items }))
})
</script>
