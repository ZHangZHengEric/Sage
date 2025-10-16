<template>
  <div class="syntax-highlighter">
    <div v-if="showHeader" class="code-header">
      <span class="language-label">{{ language || 'text' }}</span>
      <button 
        v-if="showCopyButton"
        @click="copyCode"
        class="copy-button"
        :title="copyButtonText"
      >
        <span v-if="!copied">📋</span>
        <span v-else>✅</span>
      </button>
    </div>
    <pre class="code-block"><code :class="codeClass" v-html="highlightedCode"></code></pre>
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

<style scoped>
.syntax-highlighter {
  margin: 12px 0;
  border-radius: 8px;
  overflow: hidden;
  background: #2d3748;
  border: 1px solid #4a5568;
}

.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #1a202c;
  border-bottom: 1px solid #4a5568;
}

.language-label {
  font-size: 12px;
  color: #a0aec0;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.copy-button {
  background: transparent;
  border: 1px solid #4a5568;
  color: #a0aec0;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s ease;
}

.copy-button:hover {
  background: #4a5568;
  color: #fff;
}

.code-block {
  margin: 0;
  padding: 16px;
  overflow-x: auto;
  background: #2d3748;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace;
  font-size: 14px;
  line-height: 1.5;
}

.code-block code {
  background: none;
  padding: 0;
  border-radius: 0;
  color: #e2e8f0;
}

/* 滚动条样式 */
.code-block::-webkit-scrollbar {
  height: 8px;
}

.code-block::-webkit-scrollbar-track {
  background: #1a202c;
}

.code-block::-webkit-scrollbar-thumb {
  background: #4a5568;
  border-radius: 4px;
}

.code-block::-webkit-scrollbar-thumb:hover {
  background: #718096;
}


</style>