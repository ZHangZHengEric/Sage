<template>
  <div class="docx-renderer h-full overflow-auto p-4">
    <div v-if="loading" class="flex items-center justify-center h-full text-muted-foreground">
      <div class="text-center">
        <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
        <p class="text-sm">正在解析 Word 文件...</p>
      </div>
    </div>
    <div v-else-if="error" class="flex flex-col items-center justify-center h-full text-muted-foreground">
      <FileText class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">Word 文件</p>
      <p class="text-xs text-destructive mb-4">{{ error }}</p>
      <Button variant="outline" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        打开文件
      </Button>
    </div>
    <div v-else class="docx-content prose prose-sm dark:prose-invert max-w-none" v-html="content"></div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Loader2, FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import mammoth from 'mammoth'
import DOMPurify from 'dompurify'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  fileContent: {
    type: String,
    default: ''
  }
})

const loading = ref(false)
const error = ref('')
const content = ref('')

const loadDocx = async () => {
  if (!props.fileContent) return
  
  loading.value = true
  error.value = ''
  
  try {
    // 将 base64 转换为 Uint8Array
    const binaryString = atob(props.fileContent)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }
    
    const result = await mammoth.convertToHtml({ arrayBuffer: bytes.buffer })
    content.value = DOMPurify.sanitize(result.value)
  } catch (err) {
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

onMounted(() => {
  loadDocx()
})
</script>
