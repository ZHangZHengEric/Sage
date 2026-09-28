<template>
  <div class="mermaid-renderer h-full min-h-0 overflow-auto p-4">
    <div v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
      Mermaid 渲染错误: {{ error }}
    </div>
    <div v-else-if="svg" class="mermaid-output rounded-xl border border-border/60 bg-background/80 p-4" v-html="svg"></div>
    <div v-else class="flex h-full items-center justify-center text-sm text-muted-foreground">
      正在渲染 Mermaid 图表...
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import mermaid from 'mermaid'

const props = defineProps({
  code: {
    type: String,
    default: ''
  }
})

const svg = ref('')
const error = ref('')

const sanitizeMermaidCode = (code = '') => code
  .replace(/(participant\s+\S+\s+as)\s+([^\n]+)/g, (_, prefix, label) => {
    const trimmed = label.trim()
    if (!trimmed || /^["'].*["']$/.test(trimmed)) return `${prefix} ${trimmed}`
    return `${prefix} "${trimmed.replace(/"/g, '\\"')}"`
  })

const renderDiagram = async () => {
  if (!props.code) {
    svg.value = ''
    error.value = ''
    return
  }

  try {
    await nextTick()
    mermaid.initialize({
      startOnLoad: false,
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'default',
      securityLevel: 'strict'
    })

    const diagramCode = sanitizeMermaidCode(props.code)
    const { svg: renderedSvg } = await mermaid.render(
      `workbench-mermaid-${Math.random().toString(36).slice(2)}`,
      diagramCode
    )
    svg.value = renderedSvg
    error.value = ''
  } catch (err) {
    console.error('Failed to render Mermaid diagram:', err)
    svg.value = ''
    error.value = err?.message || '未知错误'
  }
}

watch(() => props.code, renderDiagram, { immediate: true })
onMounted(renderDiagram)
</script>

<style scoped>
.mermaid-output :deep(svg) {
  @apply mx-auto h-auto max-w-full;
}
</style>
