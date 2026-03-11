<template>
  <div class="h-full flex flex-col">
    <div v-if="showHeader" class="flex items-center justify-between px-4 py-2 bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-xs text-slate-600 dark:text-slate-400 flex-none">
      <span class="font-medium uppercase tracking-wider text-[10px]">{{ language || 'text' }}</span>
      <button
        v-if="showCopyButton"
        @click="copyCode"
        class="flex items-center gap-1 hover:text-slate-800 dark:hover:text-slate-200 transition-colors focus:outline-none"
        :title="copyButtonText"
      >
        <span v-if="!copied" class="text-xs">📋</span>
        <span v-else class="text-xs">✅</span>
      </button>
    </div>
    <div class="flex-1 overflow-auto bg-slate-50 dark:bg-slate-900">
      <pre class="m-0 p-4 text-sm font-mono leading-relaxed min-w-full min-h-full text-slate-800 dark:text-slate-200"><code :class="['hljs', codeClass]" v-html="highlightedCode"></code></pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import hljs from 'highlight.js'

// 动态导入主题样式
const loadTheme = async (isDark) => {
  if (isDark) {
    await import('highlight.js/styles/atom-one-dark.css')
  } else {
    await import('highlight.js/styles/atom-one-light.css')
  }
}

// 检测当前主题
const isDarkMode = () => {
  return document.documentElement.classList.contains('dark')
}

// 初始加载
onMounted(() => {
  loadTheme(isDarkMode())
})

// 监听主题变化
watch(() => document.documentElement.classList.contains('dark'), (isDark) => {
  loadTheme(isDark)
})

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