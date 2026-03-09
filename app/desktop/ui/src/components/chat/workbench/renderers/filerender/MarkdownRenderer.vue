<template>
  <div class="markdown-preview p-4 h-full overflow-auto">
    <!-- 如果内容看起来是二进制文件，显示错误 -->
    <div v-if="isBinary" class="flex flex-col items-center justify-center h-full text-muted-foreground">
      <FileText class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">文件内容异常</p>
      <p class="text-xs text-destructive mb-4">该文件可能不是有效的 Markdown 文件</p>
      <Button variant="outline" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        打开文件
      </Button>
    </div>
    <div v-else class="prose prose-sm max-w-none dark:prose-invert markdown-workbench" v-html="renderedContent"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  content: {
    type: String,
    default: ''
  }
})

const isBinary = computed(() => {
  if (!props.content) return false
  // 检查是否以 ZIP 文件头 (PK) 开头
  if (props.content.startsWith('PK')) {
    return true
  }
  // 检查是否包含大量不可打印字符
  const sample = props.content.slice(0, 100)
  const nonPrintable = sample.match(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g)
  if (nonPrintable && nonPrintable.length > 10) {
    return true
  }
  return false
})

const renderedContent = computed(() => {
  if (!props.content) return ''
  const html = marked(props.content)
  return DOMPurify.sanitize(html)
})

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}
</script>

<style scoped>
/* Workbench Markdown Code Block Styles */
.markdown-workbench :deep(pre) {
  @apply bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700 rounded-lg p-4 my-4 overflow-auto;
}

.markdown-workbench :deep(code) {
  @apply text-slate-800 dark:text-slate-200;
}

.markdown-workbench :deep(pre code) {
  @apply bg-transparent p-0 text-sm font-mono leading-relaxed;
}
</style>
