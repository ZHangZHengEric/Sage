<template>
  <div class="rounded-lg border bg-muted/40 overflow-hidden my-4">
    <div v-if="showHeader" class="flex items-center justify-between px-4 py-2 bg-muted/50 border-b text-xs text-muted-foreground">
      <span class="font-medium uppercase tracking-wider text-[10px]">{{ language || 'text' }}</span>
      <button 
        v-if="showCopyButton"
        @click="copyCode"
        class="flex items-center gap-1 hover:text-foreground transition-colors focus:outline-none"
        :title="copyButtonText"
      >
        <span v-if="!copied" class="text-xs">📋</span>
        <span v-else class="text-xs">✅</span>
      </button>
    </div>
    <pre class="m-0 p-4 overflow-x-auto text-sm font-mono leading-relaxed bg-background/50"><code :class="['hljs', codeClass]" v-html="highlightedCode"></code></pre>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'

const props = defineProps({
  code: {
    type: String,
    required: true
  },
  language: {
    type: String,
    default: 'text'
  },
  showHeader: {
    type: Boolean,
    default: true
  },
  showCopyButton: {
    type: Boolean,
    default: true
  }
})

const copied = ref(false)

// 计算属性
const codeClass = computed(() => {
  return `language-${props.language}`
})

const escapeHtml = (text) => {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  }
  return text.replace(/[&<>"']/g, char => map[char])
}

const highlightedCode = computed(() => {
  if (!props.code) return ''
  
  try {
    // 检查语言是否支持
    if (props.language && props.language !== 'text' && hljs.getLanguage(props.language)) {
      return hljs.highlight(props.code, { language: props.language }).value
    } else {
      // 如果不支持该语言，返回原始代码（HTML转义）
      return escapeHtml(props.code)
    }
  } catch (error) {
    console.error('代码高亮失败:', error)
    return escapeHtml(props.code)
  }
})

const copyButtonText = computed(() => {
  return copied.value ? '已复制' : '复制代码'
})

const copyCode = async () => {
  try {
    await navigator.clipboard.writeText(props.code)
    copied.value = true
    
    // 2秒后重置状态
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (error) {
    console.error('复制失败:', error)
    // 降级方案：使用传统方法复制
    fallbackCopy()
  }
}

const fallbackCopy = () => {
  const textArea = document.createElement('textarea')
  textArea.value = props.code
  textArea.style.position = 'fixed'
  textArea.style.left = '-999999px'
  textArea.style.top = '-999999px'
  document.body.appendChild(textArea)
  textArea.focus()
  textArea.select()
  
  try {
    document.execCommand('copy')
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (error) {
    console.error('降级复制也失败:', error)
  } finally {
    document.body.removeChild(textArea)
  }
}
</script>