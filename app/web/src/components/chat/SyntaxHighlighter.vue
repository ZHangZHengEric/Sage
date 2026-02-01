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
    <pre class="m-0 p-4 overflow-x-auto text-sm font-mono leading-relaxed bg-background/50"><code :class="codeClass" v-html="highlightedCode"></code></pre>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import Prism from 'prismjs'
import 'prismjs/themes/prism-tomorrow.css'

// 导入常用语言支持
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-java'
import 'prismjs/components/prism-css'
import 'prismjs/components/prism-scss'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-yaml'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-go'
import 'prismjs/components/prism-rust'
import 'prismjs/components/prism-php'
import 'prismjs/components/prism-c'
import 'prismjs/components/prism-cpp'

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

const highlightedCode = computed(() => {
  if (!props.code) return ''
  
  try {
    // 检查语言是否支持
    if (Prism.languages[props.language]) {
      return Prism.highlight(props.code, Prism.languages[props.language], props.language)
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

// 方法
const escapeHtml = (text) => {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

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