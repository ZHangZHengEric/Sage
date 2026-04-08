<template>
  <div class="file-renderer h-full min-h-0 flex flex-col overflow-hidden">
    <!-- 整合后的头部：包含 ItemHeader 信息和文件操作 -->
    <div class="workbench-header flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-muted/30 px-3 py-2.5 flex-none">
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <!-- ItemHeader 信息 -->
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="header-divider text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="header-divider text-muted-foreground/50">|</span>
        <!-- 文件信息 -->
        <span class="text-xl">{{ fileIcon }}</span>
        <span class="text-sm font-medium truncate">{{ displayFileName }}</span>
        <Badge variant="secondary" class="text-xs">{{ fileTypeLabel }}</Badge>
      </div>
      <div class="workbench-actions flex w-full flex-wrap items-center gap-1 sm:w-auto sm:justify-end">
        <Button
          v-if="canPreviewInDialog"
          variant="ghost"
          size="sm"
          @click="previewDialogOpen = true"
          class="workbench-action-button h-7 px-2"
          :title="t('workbench.view')"
        >
          <Eye class="w-4 h-4 sm:mr-1" />
          <span class="workbench-action-label">{{ t('workbench.view') }}</span>
        </Button>
        <Button 
          v-if="canCopy"
          variant="ghost" 
          size="sm"
          @click="copyContent"
          class="workbench-action-button h-7 px-2"
        >
          <Copy v-if="!copied" class="w-4 h-4 sm:mr-1" />
          <Check v-else class="w-4 h-4 text-green-500 sm:mr-1" />
          <span class="workbench-action-label">{{ copied ? (t('common.copied') || '已复制') : t('common.copy') }}</span>
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          @click="openFile"
          class="workbench-action-button h-7 px-2"
          :title="t('workspace.download')"
        >
          <Download class="w-4 h-4 sm:mr-1" />
          <span class="workbench-action-label">{{ t('workspace.download') }}</span>
        </Button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 min-h-0 overflow-auto">
      <!-- 加载中 -->
      <div v-if="loading" class="flex items-center justify-center h-full">
        <Loader2 class="w-6 h-6 animate-spin text-primary" />
        <span class="ml-2 text-sm text-muted-foreground">{{ t('common.loading') }}</span>
      </div>

      <!-- 错误 -->
      <div v-else-if="error" class="p-4 text-destructive bg-destructive/10 h-full flex flex-col items-center justify-center">
        <AlertCircle class="w-8 h-8 mb-2" />
        <span class="text-sm">{{ error }}</span>
        <Button 
          variant="outline" 
          size="sm"
          @click="loadContent"
          class="mt-3"
        >
          <RefreshCw class="w-4 h-4 mr-1" />
          {{ t('common.retry') || '重试' }}
        </Button>
      </div>

      <!-- PDF 预览 -->
      <PdfRenderer v-else-if="fileType === 'pdf'" :file-url="blobUrl" />

      <!-- 图片预览 -->
      <ImageRenderer v-else-if="fileType === 'image'" :file-url="blobUrl" :file-name="displayFileName" />

      <!-- HTML 预览 -->
      <HtmlRenderer v-else-if="fileType === 'html'" :file-path="filePath" :content="fileContent" />

      <!-- Markdown 预览 -->
      <MarkdownRenderer v-else-if="fileType === 'markdown'" :file-path="filePath" :content="fileContent" />

      <!-- 代码文件预览 -->
      <CodeRenderer v-else-if="fileType === 'code'" :content="fileContent" :language="language" />

      <!-- Excalidraw 预览 -->
      <div v-else-if="fileType === 'excalidraw'" class="excalidraw-preview h-full">
        <ExcalidrawRenderer
          v-if="excalidrawData"
          :data="excalidrawData"
          :theme="isDark ? 'dark' : 'light'"
          class="w-full h-full"
        />
      </div>

      <!-- 文本文件预览 -->
      <TextRenderer v-else-if="fileType === 'text'" :content="fileContent" />

      <!-- Office 文件预览 -->
      <DocxRenderer v-else-if="fileType === 'office' && (fileExtension === 'docx' || fileExtension === 'doc')" :file-content="fileArrayBuffer" :file-url="blobUrl" />
      <XlsxRenderer v-else-if="fileType === 'office' && (fileExtension === 'xlsx' || fileExtension === 'xls')" :file-content="fileArrayBuffer" :file-url="blobUrl" />
      <PptxRenderer v-else-if="fileType === 'office' && (fileExtension === 'pptx' || fileExtension === 'ppt')" :file-data="fileArrayBuffer" :file-url="blobUrl" />
      <div v-else-if="fileType === 'office'" class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <FileText class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">{{ officeFileType }} 文件</p>
        <p class="text-xs text-muted-foreground/60 mb-4">此格式暂不支持预览</p>
        <Button variant="outline" size="sm" @click="openFile">
          <Download class="w-4 h-4 mr-1" />
          下载文件
        </Button>
      </div>

      <!-- 其他文件 -->
      <div v-else class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <File class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">此文件类型暂不支持预览</p>
        <p class="text-xs text-muted-foreground/60 mb-4">{{ displayFileName }}</p>
        <Button 
          variant="outline" 
          size="sm"
          @click="openFile"
        >
          <Download class="w-4 h-4 mr-1" />
          下载文件
        </Button>
      </div>
    </div>
  </div>

  <Dialog v-if="!dialogMode" v-model:open="previewDialogOpen">
    <DialogContent class="max-w-[90vw] h-[85vh] p-0 overflow-hidden flex flex-col">
      <FileRenderer
        :file-path="filePath"
        :file-name="fileName"
        :item="item"
        :dialog-mode="true"
      />
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, defineAsyncComponent, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useLanguage } from '@/utils/i18n.js'
import {
  Loader2,
  AlertCircle,
  RefreshCw,
  Copy,
  Check,
  File,
  FileText,
  Download,
  Eye
} from 'lucide-vue-next'
import { useThemeStore } from '@/stores/theme'
import PdfRenderer from './filerender/PdfRenderer.vue'
import ImageRenderer from './filerender/ImageRenderer.vue'
import TextRenderer from './filerender/TextRenderer.vue'
import { agentAPI } from '@/api/agent'

import { 
  getFileExtension, 
  getFileType, 
  getFileTypeLabel, 
  getFileIcon, 
  getFileLanguage, 
  getOfficeFileType,
  getDisplayFileName,
  normalizeFilePath
} from '@/utils/fileIcons.js'

const HtmlRenderer = defineAsyncComponent(() => import('./filerender/HtmlRenderer.vue'))
const MarkdownRenderer = defineAsyncComponent(() => import('./filerender/MarkdownRenderer.vue'))
const CodeRenderer = defineAsyncComponent(() => import('./filerender/CodeRenderer.vue'))
const ExcalidrawRenderer = defineAsyncComponent(() => import('./filerender/ExcalidrawRenderer.vue'))
const DocxRenderer = defineAsyncComponent(() => import('./filerender/DocxRenderer.vue'))
const XlsxRenderer = defineAsyncComponent(() => import('./filerender/XlsxRenderer.vue'))
const PptxRenderer = defineAsyncComponent(() => import('./filerender/PptxRenderer.vue'))

const props = defineProps({
  filePath: {
    type: String,
    required: true
  },
  fileName: {
    type: String,
    default: ''
  },
  item: {
    type: Object,
    default: null
  },
  dialogMode: {
    type: Boolean,
    default: false
  }
})

// 状态
const loading = ref(false)
const error = ref(null)
const fileContent = ref('') // 文本内容
const fileArrayBuffer = ref(null) // 二进制内容
const blobUrl = ref('') // Blob URL
const copied = ref(false)
const previewDialogOpen = ref(false)
const { t } = useLanguage()

// 主题
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': t('workbench.tool.role.ai'),
    'user': t('workbench.tool.role.user'),
    'system': t('workbench.tool.role.system'),
    'tool': t('workbench.tool.role.tool')
  }
  return roleMap[props.item?.role] || t('workbench.tool.role.ai')
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}

// 文件信息
const displayFileName = computed(() => {
  return getDisplayFileName(props.filePath, props.fileName)
})

const fileExtension = computed(() => {
  return getFileExtension(props.filePath, displayFileName.value)
})

// 检测是否为在线图片 URL
const isOnlineImageUrl = computed(() => {
  const path = props.filePath || ''
  const isHttpUrl = path.startsWith('http://') || path.startsWith('https://')
  if (!isHttpUrl) return false
  // 检查是否是图片扩展名
  return ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp'].includes(fileExtension.value)
})

// 文件类型检测
const fileType = computed(() => {
  // 如果是在线图片 URL，返回 image 类型
  if (isOnlineImageUrl.value) return 'image'
  return getFileType(fileExtension.value)
})

const fileTypeLabel = computed(() => {
  return getFileTypeLabel(fileExtension.value, officeFileType.value)
})

// 文件图标
const fileIcon = computed(() => {
  return getFileIcon(fileExtension.value)
})

// 编程语言
const language = computed(() => {
  return getFileLanguage(fileExtension.value)
})

// Office 文件类型名称
const officeFileType = computed(() => {
  return getOfficeFileType(fileExtension.value)
})

// 是否可以复制
const canCopy = computed(() => {
  return ['code', 'text', 'markdown'].includes(fileType.value)
})

const canPreviewInDialog = computed(() => {
  if (props.dialogMode) return false
  return ['pdf', 'image', 'html', 'markdown', 'code', 'excalidraw', 'text', 'office'].includes(fileType.value)
})

// Excalidraw 特定数据
const excalidrawElementCount = ref(0)
const excalidrawTypeSummary = ref('')
const excalidrawWidth = ref(800)
const excalidrawHeight = ref(600)
const excalidrawSvg = ref('')
const excalidrawData = ref(null)

// 生成 Excalidraw SVG (保持原样)
const generateExcalidrawSvg = (data) => {
  if (!data.elements || !Array.isArray(data.elements)) return ''
  
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  
  data.elements.forEach(el => {
    const w = el.width || 100
    const h = el.height || 100
    if (el.x !== undefined) {
      minX = Math.min(minX, el.x)
      maxX = Math.max(maxX, el.x + w)
    }
    if (el.y !== undefined) {
      minY = Math.min(minY, el.y)
      maxY = Math.max(maxY, el.y + h)
    }
  })
  
  const padding = 50
  excalidrawWidth.value = Math.max(400, maxX - minX + padding * 2)
  excalidrawHeight.value = Math.max(300, maxY - minY + padding * 2)
  
  let svgElements = ''
  data.elements.slice(0, 100).forEach(el => {
    const x = (el.x || 0) - minX + padding
    const y = (el.y || 0) - minY + padding
    const w = el.width || 100
    const h = el.height || 100
    const fill = el.backgroundColor || 'transparent'
    const stroke = el.strokeColor || '#1e1e1e'
    const strokeWidth = el.strokeWidth || 1
    const opacity = el.opacity !== undefined ? el.opacity : 1
    
    const style = `fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" opacity="${opacity}"`
    
    switch (el.type) {
      case 'rectangle':
        const rx = el.roundness?.value || 0
        svgElements += `<rect x="${x}" y="${y}" width="${w}" height="${h}" ${style} rx="${rx}"/>`
        break
      case 'ellipse':
        svgElements += `<ellipse cx="${x + w/2}" cy="${y + h/2}" rx="${w/2}" ry="${h/2}" ${style}/>`
        break
      // ... 简化 ...
    }
  })
  
  return svgElements
}

// 加载文件内容
const loadContent = async () => {
  try {
    loading.value = true
    error.value = null

    // 如果是在线图片 URL，直接使用该 URL 预览
    if (isOnlineImageUrl.value) {
      blobUrl.value = props.filePath
      loading.value = false
      return
    }

    // 获取 Agent ID
    const agentId = props.item?.agentId
    const sessionId = props.item?.sessionId
    if (!agentId) {
      // 历史消息恢复时 agentId 可能晚于 workbench item 到达，这里先等待回填。
      loading.value = false
      return
    }

    // Clean path
    const safePath = normalizeFilePath(props.filePath)

    // 下载文件 Blob
    const blob = await agentAPI.downloadFile(agentId, safePath, sessionId)

    // 创建 Blob URL 用于预览（图片、PDF）
    if (blobUrl.value) {
        URL.revokeObjectURL(blobUrl.value)
    }
    blobUrl.value = URL.createObjectURL(blob)
    
    // 根据文件类型处理内容
    if (['pdf', 'image'].includes(fileType.value)) {
      // 图片和 PDF 直接使用 blobUrl，不需要额外处理内容
      loading.value = false
      return
    }
    
    // 对于 Office 文件，获取 ArrayBuffer
    if (fileType.value === 'office') {
        fileArrayBuffer.value = await blob.arrayBuffer()
        loading.value = false
        return
    }

    // 对于文本类文件，获取文本内容
    fileContent.value = await blob.text()

    if (fileType.value === 'excalidraw') {
      try {
        const data = JSON.parse(fileContent.value)
        // ... Excalidraw 处理逻辑 ...
        excalidrawElementCount.value = data.elements?.length || 0
        
        // 简化的 Excalidraw 数据处理
        excalidrawData.value = {
          elements: data.elements || [],
          appState: {
            ...data.appState,
            viewBackgroundColor: data.appState?.viewBackgroundColor || '#ffffff'
          },
          files: data.files || {}
        }
      } catch (e) {
        console.warn('解析 Excalidraw 数据失败:', e)
      }
    }

    loading.value = false
  } catch (err) {
    console.error('加载文件失败:', err)
    error.value = `加载失败: ${err.message}`
    loading.value = false
  }
}

// 打开文件 (下载)
const openFile = async () => {
  // 如果是在线图片 URL，直接在新标签页打开
  if (isOnlineImageUrl.value) {
    window.open(props.filePath, '_blank')
    return
  }

  if (blobUrl.value) {
    const a = document.createElement('a')
    a.href = blobUrl.value
    a.download = props.fileName || props.filePath.split('/').pop() || 'download'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } else {
    // 如果没有加载过，尝试触发下载
    try {
       const agentId = props.item?.agentId
       const sessionId = props.item?.sessionId
       if (agentId) {
           const safePath = normalizeFilePath(props.filePath)
           const blob = await agentAPI.downloadFile(agentId, safePath, sessionId)
           const url = URL.createObjectURL(blob)
           const a = document.createElement('a')
           a.href = url
           a.download = props.fileName || props.filePath.split('/').pop() || 'download'
           document.body.appendChild(a)
           a.click()
           document.body.removeChild(a)
           setTimeout(() => URL.revokeObjectURL(url), 1000)
       }
    } catch (e) {
        console.error('下载失败', e)
    }
  }
}

// 复制内容
const copyContent = async () => {
  try {
    await navigator.clipboard.writeText(fileContent.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (err) {
    console.error('复制失败:', err)
  }
}

// 自动加载
onMounted(() => {
  loadContent()
})

watch(() => props.item?.agentId, (agentId, previousAgentId) => {
  if (!agentId || agentId === previousAgentId) return
  if (!blobUrl.value && !fileContent.value && !fileArrayBuffer.value) {
    loadContent()
  }
})

// 清理
onUnmounted(() => {
  if (blobUrl.value) {
    URL.revokeObjectURL(blobUrl.value)
  }
})
</script>

<style scoped>
.file-renderer {
  height: 100%;
}

@media (max-width: 640px) {
  .workbench-actions {
    width: 100%;
  }

  .workbench-action-button {
    flex: 0 0 auto;
  }
}

@media (max-width: 520px) {
  .workbench-action-label,
  .header-divider {
    display: none;
  }

  .workbench-action-button {
    padding-left: 0.5rem;
    padding-right: 0.5rem;
  }
}
</style>
