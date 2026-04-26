<template>
  <div class="h-full min-h-0 flex flex-col bg-background">
    <div class="flex items-center justify-between gap-3 px-4 py-3 border-b border-border bg-muted/30">
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <span class="text-xl">{{ fileIcon }}</span>
        <div class="min-w-0">
          <p class="text-sm font-medium truncate">{{ item?.name || item?.path }}</p>
          <p class="text-xs text-muted-foreground">{{ fileTypeLabel }}</p>
        </div>
      </div>
      <div class="flex items-center gap-1 shrink-0">
        <Button variant="ghost" size="sm" class="h-8 px-2" @click="$emit('download-file', item)">
          <Download class="w-4 h-4 mr-1" />
          下载
        </Button>
        <Button variant="ghost" size="sm" class="h-8 w-8 px-0" @click="$emit('close')">
          <X class="w-4 h-4" />
        </Button>
      </div>
    </div>

    <div class="flex-1 min-h-0 overflow-auto">
      <div v-if="loading" class="h-full flex flex-col items-center justify-center text-muted-foreground">
        <Loader2 class="w-8 h-8 animate-spin mb-2 text-primary" />
        <p class="text-sm">加载中...</p>
      </div>

      <div v-else-if="error" class="h-full flex flex-col items-center justify-center text-muted-foreground p-6">
        <AlertCircle class="w-10 h-10 mb-3 text-destructive" />
        <p class="text-sm mb-3">{{ error }}</p>
        <Button variant="outline" size="sm" @click="loadContent">
          <RefreshCw class="w-4 h-4 mr-1" />
          重试
        </Button>
      </div>

      <div v-else-if="fileType === 'image'" class="h-full flex items-center justify-center bg-muted/20 p-4">
        <img :src="blobUrl" :alt="item?.name" class="max-w-full max-h-full object-contain" />
      </div>

      <iframe
        v-else-if="fileType === 'pdf'"
        :src="blobUrl"
        class="w-full h-full border-0 bg-white"
        title="PDF Preview"
      />

      <iframe
        v-else-if="fileType === 'html'"
        :src="htmlUrl"
        class="w-full h-full border-0 bg-white"
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        title="HTML Preview"
      />

      <MarkdownRenderer
        v-else-if="fileType === 'markdown'"
        file-path=""
        :content="fileContent"
      />

      <CodeRenderer
        v-else-if="fileType === 'code'"
        :content="fileContent"
        :language="language"
      />

      <TextRenderer
        v-else-if="fileType === 'text'"
        :content="fileContent"
      />

      <DocxRenderer
        v-else-if="fileType === 'office' && (fileExtension === 'docx' || fileExtension === 'doc')"
        :file-content="fileBase64"
      />

      <XlsxRenderer
        v-else-if="fileType === 'office' && (fileExtension === 'xlsx' || fileExtension === 'xls')"
        :file-content="fileBase64"
      />

      <!-- 视频预览 -->
      <div v-else-if="fileType === 'video'" class="h-full relative flex items-center justify-center bg-black">
        <video
          v-if="videoStreamUrl && !videoError"
          :src="videoStreamUrl"
          class="max-w-full max-h-full object-contain"
          controls
          preload="metadata"
          @error="handleVideoError"
        />
        <div v-if="videoError" class="flex flex-col items-center justify-center text-white p-6 gap-2">
          <span class="text-4xl">🎬</span>
          <p class="text-sm text-white/70 text-center">{{ videoError }}</p>
        </div>
        <div v-if="!videoStreamUrl && !videoError" class="flex flex-col items-center justify-center text-white/50">
          <Loader2 class="w-8 h-8 animate-spin" />
        </div>
      </div>

      <div v-else class="h-full flex flex-col items-center justify-center text-muted-foreground p-6 bg-muted/20">
        <File class="w-14 h-14 mb-3 opacity-50" />
        <p class="text-sm mb-1">此文件类型暂不支持预览</p>
        <p class="text-xs opacity-70">{{ item?.name || item?.path }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { AlertCircle, Download, File, Loader2, RefreshCw, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { taskAPI } from '@/api/task.js'
import CodeRenderer from './workbench/renderers/filerender/CodeRenderer.vue'
import MarkdownRenderer from './workbench/renderers/filerender/MarkdownRenderer.vue'
import TextRenderer from './workbench/renderers/filerender/TextRenderer.vue'
import DocxRenderer from './workbench/renderers/filerender/DocxRenderer.vue'
import XlsxRenderer from './workbench/renderers/filerender/XlsxRenderer.vue'

const VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov', 'm4v', 'mkv', 'avi', 'flv', 'ogv']

const props = defineProps({
  item: {
    type: Object,
    required: true
  },
  agentId: {
    type: String,
    default: ''
  }
})

defineEmits(['download-file', 'close'])

const loading = ref(false)
const error = ref('')
const blobUrl = ref('')
const htmlUrl = ref('')
const fileContent = ref('')
const fileBase64 = ref('')
const videoStreamUrl = ref('')
const videoError = ref('')

const fileExtension = computed(() => {
  const name = props.item?.name || props.item?.path || ''
  const match = name.match(/\.([^.]+)$/)
  return match ? match[1].toLowerCase() : ''
})

const fileType = computed(() => {
  const ext = fileExtension.value
  if (VIDEO_EXTENSIONS.includes(ext)) return 'video'
  const typeMap = {
    pdf: 'pdf',
    png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', svg: 'image', bmp: 'image',
    html: 'html', htm: 'html',
    md: 'markdown', markdown: 'markdown',
    js: 'code', ts: 'code', jsx: 'code', tsx: 'code',
    py: 'code', java: 'code', go: 'code', rs: 'code', c: 'code', cpp: 'code',
    json: 'code', xml: 'code', yaml: 'code', yml: 'code', css: 'code', scss: 'code', less: 'code',
    vue: 'code', svelte: 'code', php: 'code', rb: 'code', swift: 'code', kt: 'code', sql: 'code', sh: 'code', bash: 'code', zsh: 'code',
    txt: 'text', log: 'text', csv: 'text',
    docx: 'office', doc: 'office', xlsx: 'office', xls: 'office'
  }
  return typeMap[ext] || 'other'
})

const fileTypeLabel = computed(() => {
  const labels = {
    pdf: 'PDF',
    image: '图片',
    video: '视频',
    html: 'HTML',
    markdown: 'Markdown',
    code: '代码',
    text: '文本',
    office: 'Office',
    other: '文件'
  }
  return labels[fileType.value] || '文件'
})

const fileIcon = computed(() => {
  const iconMap = {
    pdf: '📕',
    image: '🖼️',
    video: '🎬',
    html: '🌐',
    markdown: '📝',
    code: '📜',
    text: '📃',
    office: '📘',
    other: '📎'
  }
  return iconMap[fileType.value] || '📎'
})

const language = computed(() => {
  const langMap = {
    js: 'JavaScript', ts: 'TypeScript', jsx: 'JSX', tsx: 'TSX',
    py: 'Python', java: 'Java', go: 'Go', rs: 'Rust',
    c: 'C', cpp: 'C++', json: 'JSON', xml: 'XML', yaml: 'YAML', yml: 'YAML',
    css: 'CSS', scss: 'SCSS', less: 'Less', vue: 'Vue', svelte: 'Svelte',
    php: 'PHP', rb: 'Ruby', swift: 'Swift', kt: 'Kotlin', sql: 'SQL', sh: 'Shell', bash: 'Bash', zsh: 'Zsh'
  }
  return langMap[fileExtension.value] || fileExtension.value || 'text'
})

const revokeUrls = () => {
  if (blobUrl.value) {
    URL.revokeObjectURL(blobUrl.value)
    blobUrl.value = ''
  }
  if (htmlUrl.value) {
    URL.revokeObjectURL(htmlUrl.value)
    htmlUrl.value = ''
  }
}

const handleVideoError = (e) => {
  const msg = e?.target?.error?.message || '格式不支持或文件损坏'
  videoError.value = `视频播放失败: ${msg}`
}

const loadContent = async () => {
  if (!props.agentId || !props.item?.path) {
    error.value = '文件信息不完整'
    return
  }

  loading.value = true
  error.value = ''
  videoError.value = ''
  fileContent.value = ''
  fileBase64.value = ''
  videoStreamUrl.value = ''
  revokeUrls()

  // 视频：直接构造流式 URL，后端 FileResponse 支持 Range 请求，无需下载整个文件
  if (fileType.value === 'video') {
    videoStreamUrl.value = taskAPI.getFileStreamUrl(props.agentId, props.item.path)
    loading.value = false
    return
  }

  try {
    const blob = await taskAPI.downloadFile(props.agentId, props.item.path)
    blobUrl.value = URL.createObjectURL(blob)

    if (fileType.value === 'image' || fileType.value === 'pdf') {
      return
    }

    if (fileType.value === 'html') {
      fileContent.value = await blob.text()
      htmlUrl.value = URL.createObjectURL(new Blob([fileContent.value], { type: 'text/html' }))
      return
    }

    if (fileType.value === 'office') {
      const arrayBuffer = await blob.arrayBuffer()
      const bytes = new Uint8Array(arrayBuffer)
      let binary = ''
      bytes.forEach(byte => {
        binary += String.fromCharCode(byte)
      })
      fileBase64.value = btoa(binary)
      return
    }

    fileContent.value = await blob.text()
  } catch (err) {
    console.error('加载工作空间文件失败:', err)
    error.value = err?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadContent()
})

onUnmounted(() => {
  revokeUrls()
})
</script>
