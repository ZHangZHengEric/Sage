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
import { computed, onMounted, watch, nextTick, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import mermaid from 'mermaid'
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

const contentRef = ref(null)
const isRendering = ref(false)

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

// Mermaid 图表列表
const mermaidList = []

// 自定义 marked renderer 来处理 mermaid
const renderer = new marked.Renderer()

renderer.code = (token) => {
  const code = token.text
  const language = token.lang
  if (language === 'mermaid') {
    const id = `mermaid-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    mermaidList.push({ id, code })
    // 返回 loading 状态的占位符
    return `<div class="mermaid-chart" id="${id}">
      <div class="flex items-center justify-center p-8 bg-muted/30 rounded-lg border border-border/50">
        <div class="flex items-center gap-3 text-muted-foreground">
          <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span class="text-sm">正在渲染图表...</span>
        </div>
      </div>
    </div>`
  }
  return `<pre><code class="language-${language}">${code}</code></pre>`
}

marked.setOptions({ renderer })

const renderedContent = computed(() => {
  if (!props.content) return ''
  // 清空 mermaid 列表
  mermaidList.length = 0
  const html = marked(props.content)
  return DOMPurify.sanitize(html)
})

// 渲染 Mermaid 图表 - 使用 requestIdleCallback 避免阻塞主线程
const renderMermaid = async () => {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 50))

  if (mermaidList.length === 0) return

  isRendering.value = true

  // 初始化 mermaid
  mermaid.initialize({
    startOnLoad: false,
    theme: document.documentElement.classList.contains('dark') ? 'dark' : 'default',
    securityLevel: 'loose'
  })

  // 使用 requestIdleCallback 或 setTimeout 分批渲染，避免阻塞主线程
  const renderBatch = async (items, batchSize = 3) => {
    for (let i = 0; i < items.length; i += batchSize) {
      const batch = items.slice(i, i + batchSize)

      // 每批渲染前让出主线程
      if (i > 0) {
        await new Promise(resolve => {
          if (typeof requestIdleCallback !== 'undefined') {
            requestIdleCallback(resolve, { timeout: 100 })
          } else {
            setTimeout(resolve, 0)
          }
        })
      }

      // 渲染当前批次
      await Promise.all(batch.map(async ({ id, code }) => {
        const el = document.getElementById(id)
        if (!el) return

        try {
          // 使用 mermaid.render 生成 SVG
          const { svg } = await mermaid.render(`mermaid-svg-${id}`, code)
          el.innerHTML = svg
          el.classList.add('mermaid-rendered')
        } catch (err) {
          console.error(`Mermaid 图表 ${id} 渲染失败:`, err)
          el.innerHTML = `<pre class="text-destructive p-4 border border-destructive/50 rounded bg-destructive/10">Mermaid 渲染错误: ${err.message}</pre>`
        }
      }))
    }
  }

  await renderBatch(mermaidList)
  isRendering.value = false
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

// 监听内容变化，重新渲染 mermaid
watch(() => props.content, async () => {
  await renderMermaid()
}, { immediate: true })

onMounted(() => {
  renderMermaid()
})
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

/* Mermaid Chart Styles */
.markdown-workbench :deep(.mermaid-chart) {
  @apply my-4;
}

.markdown-workbench :deep(.mermaid-chart svg) {
  @apply mx-auto max-w-full;
}
</style>
