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
import { computed, nextTick, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import mermaid from 'mermaid'
import { FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { isMermaidLanguage } from './drawio'

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

const renderer = new marked.Renderer()
const mermaidList = []

renderer.code = (token) => {
  const code = token.text
  const language = token.lang
  if (isMermaidLanguage(language)) {
    const id = `workbench-mermaid-${Date.now()}-${Math.random().toString(36).slice(2)}`
    mermaidList.push({ id, code })
    return `<div class="mermaid-chart not-prose" id="${id}">${escapeHtml(code)}</div>`
  }
  return `<pre><code class="language-${language || 'text'}">${escapeHtml(code)}</code></pre>`
}

marked.setOptions({ renderer, breaks: true })

const renderedContent = computed(() => {
  if (!props.content) return ''
  mermaidList.length = 0
  const html = marked(props.content)
  return DOMPurify.sanitize(html)
})

const escapeHtml = (content) => String(content)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

const sanitizeMermaidCode = (code = '') => code
  .replace(/(participant\s+\S+\s+as)\s+([^\n]+)/g, (_, prefix, label) => {
    const trimmed = label.trim()
    if (!trimmed || /^["'].*["']$/.test(trimmed)) return `${prefix} ${trimmed}`
    return `${prefix} "${trimmed.replace(/"/g, '\\"')}"`
  })

const renderMermaid = async () => {
  await nextTick()
  mermaid.initialize({
    startOnLoad: false,
    theme: document.documentElement.classList.contains('dark') ? 'dark' : 'default',
    securityLevel: 'strict'
  })

  for (const { id, code } of mermaidList) {
    const el = document.getElementById(id)
    if (!el) continue

    try {
      const { svg } = await mermaid.render(`svg-${id}`, sanitizeMermaidCode(code))
      el.innerHTML = svg
    } catch (err) {
      console.error('Failed to render Mermaid in markdown:', err)
      el.innerHTML = `<pre class="text-destructive p-4 border border-destructive/50 rounded bg-destructive/10">Mermaid 渲染错误: ${escapeHtml(err?.message || '未知错误')}</pre>`
    }
  }
}

watch(() => renderedContent.value, renderMermaid, { immediate: true })
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

.markdown-workbench :deep(.mermaid-chart) {
  @apply my-4 overflow-hidden rounded-xl border border-border/60 bg-background/70;
}

.markdown-workbench :deep(.mermaid-chart svg) {
  @apply mx-auto h-auto max-w-full;
}
</style>
