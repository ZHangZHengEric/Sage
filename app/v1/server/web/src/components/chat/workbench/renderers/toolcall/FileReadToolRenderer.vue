<template>
  <div class="h-full flex flex-col">
    <div class="file-header px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
      <FileText class="w-4 h-4" />
      <span class="font-medium text-sm">{{ readFilePath }}</span>
      <Badge variant="secondary" class="text-xs">{{ readFileType }}</Badge>
      <Badge v-if="fileReadRangeLabel" variant="outline" class="text-xs">{{ fileReadRangeLabel }}</Badge>
    </div>
    <div class="file-content flex-1 overflow-auto p-4">
      <div v-if="fileReadErrorMessage" class="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
        {{ fileReadErrorMessage }}
      </div>
      <div
        v-else-if="fileReadHasLineNumbers"
        class="overflow-auto rounded-lg border border-border/50 bg-muted/10 font-mono text-sm"
      >
        <div
          v-for="(entry, index) in fileReadLineEntries"
          :key="`${entry.lineNumber}-${index}`"
          class="flex border-b border-border/30 last:border-b-0"
        >
          <div class="w-16 flex-shrink-0 select-none border-r border-border/40 bg-muted/30 px-3 py-1 text-right text-xs text-muted-foreground">
            {{ entry.lineNumber }}
          </div>
          <pre class="min-w-0 flex-1 whitespace-pre-wrap break-all px-3 py-1 text-foreground">{{ entry.text || ' ' }}</pre>
        </div>
      </div>
      <SyntaxHighlighter
        v-else-if="isCodeFile(readFileType)"
        :code="fileContent"
        :language="readFileType"
      />
      <MarkdownRenderer
        v-else-if="readFileType === 'markdown'"
        :content="fileContent"
      />
      <img
        v-else-if="isImageFile(readFileType)"
        :src="fileContent"
        class="max-w-full h-auto"
      />
      <pre v-else class="whitespace-pre-wrap text-sm">{{ fileContent }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FileText } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import SyntaxHighlighter from '@/components/chat/SyntaxHighlighter.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'

const props = defineProps({
  toolArgs: {
    type: Object,
    default: () => ({})
  },
  toolResult: {
    type: Object,
    default: null
  }
})

const readFilePath = computed(() => props.toolArgs.file_path || '')
const readFileType = computed(() => {
  const path = readFilePath.value
  const ext = path.split('.').pop()?.toLowerCase()
  const typeMap = {
    py: 'python',
    js: 'javascript',
    ts: 'typescript',
    vue: 'vue',
    html: 'html',
    css: 'css',
    json: 'json',
    md: 'markdown',
    txt: 'text',
    yml: 'yaml',
    yaml: 'yaml',
    sh: 'bash',
    png: 'image',
    jpg: 'image',
    jpeg: 'image',
    gif: 'image',
    svg: 'image'
  }
  return typeMap[ext] || ext || 'text'
})
const fileReadResult = computed(() => {
  const content = props.toolResult?.content
  if (!content) return null
  try {
    return typeof content === 'string' ? JSON.parse(content) : content
  } catch {
    return null
  }
})
const fileReadErrorMessage = computed(() => {
  if (props.toolResult?.is_error) {
    const content = props.toolResult?.content
    if (typeof content === 'string') return content
    return content?.message || content?.error || JSON.stringify(content)
  }

  const result = fileReadResult.value
  if (!result) return ''
  if (result.status === 'error') {
    return result.message || result.error || result.detail || '读取文件失败'
  }
  if (result.error && !result.raw_content && !result.content && !result.data) {
    return typeof result.error === 'string' ? result.error : JSON.stringify(result.error)
  }
  return ''
})
const fileContent = computed(() => {
  const content = props.toolResult?.content
  if (!content) return ''
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    if (parsed?.status === 'error') {
      return ''
    }
    return parsed.raw_content || parsed.content || parsed.data || parsed
  } catch {
    return content
  }
})
const fileReadHasLineNumbers = computed(() => Boolean(fileReadResult.value?.line_numbers_included))
const fileReadRangeLabel = computed(() => {
  const result = fileReadResult.value
  if (!result || typeof result.start_line !== 'number' || typeof result.end_line !== 'number') {
    return ''
  }
  return `L${result.start_line + 1}-L${result.end_line}`
})
const fileReadLineEntries = computed(() => {
  if (!fileReadHasLineNumbers.value) return []
  const numberedContent = fileReadResult.value?.content
  if (typeof numberedContent !== 'string' || !numberedContent.length) return []
  return numberedContent.split('\n').map((line) => {
    const match = line.match(/^\s*(\d+)\s*\|\s?(.*)$/)
    if (!match) return { lineNumber: '', text: line }
    return { lineNumber: match[1], text: match[2] ?? '' }
  })
})

const isCodeFile = (type) => ['python', 'javascript', 'typescript', 'vue', 'html', 'css', 'json', 'yaml', 'bash'].includes(type)
const isImageFile = (type) => type === 'image'
</script>
