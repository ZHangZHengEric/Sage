<template>
  <div class="file-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合后的头部：包含 ItemHeader 信息和文件操作 -->
    <div class="workbench-header flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-muted/30 px-3 py-2.5 flex-none">
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <!-- ItemHeader 信息 -->
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="header-divider text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="header-divider text-muted-foreground/50">|</span>
        <!-- 文件信息 -->
        <span class="text-xl">{{ isDirectory ? '📁' : fileIcon }}</span>
        <span class="text-sm font-medium truncate">{{ displayFileName }}</span>
        <Badge variant="secondary" class="text-xs">{{ isDirectory ? '文件夹' : fileTypeLabel }}</Badge>
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
          v-if="!isDirectory && canCopy"
          variant="ghost" 
          size="sm"
          @click="copyContent"
          class="workbench-action-button h-7 px-2"
        >
          <Copy v-if="!copied" class="w-4 h-4 sm:mr-1" />
          <Check v-else class="w-4 h-4 text-green-500 sm:mr-1" />
          <span class="workbench-action-label">{{ copied ? '已复制' : '复制' }}</span>
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          @click="downloadFile"
          class="workbench-action-button h-7 px-2"
          :title="isDirectory ? '下载文件夹' : '下载文件'"
        >
          <Download class="w-4 h-4 sm:mr-1" />
          <span class="workbench-action-label">下载</span>
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          @click="openFile"
          class="workbench-action-button h-7 px-2"
          :title="isDirectory ? '打开文件夹' : '打开文件'"
        >
          <ExternalLink class="w-4 h-4 sm:mr-1" />
          <span class="workbench-action-label">打开</span>
        </Button>
        <Button
          v-if="drawioOpenUrl"
          variant="ghost"
          size="sm"
          @click="openInDrawio"
          class="workbench-action-button h-7 px-2"
          title="在 draw.io 中打开"
        >
          <Globe class="w-4 h-4 sm:mr-1" />
          <span class="workbench-action-label">draw.io</span>
        </Button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 overflow-auto">
      <!-- 无文件路径 -->
      <div v-if="!filePath" class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <File class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">未指定文件路径</p>
      </div>

      <!-- 加载中 -->
      <div v-else-if="loading" class="flex items-center justify-center h-full">
        <Loader2 class="w-6 h-6 animate-spin text-primary" />
        <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
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
          重试
        </Button>
      </div>

      <!-- 文件夹视图 - 使用 WorkspaceFileTree -->
      <div v-else-if="isDirectory" class="h-full p-4">
        <div v-if="directoryTree.length > 0" class="space-y-1">
          <WorkspaceFileTree
            v-for="node in directoryTree"
            :key="node.path"
            :item="node"
            @download="handleDownload"
            @delete="handleDelete"
            @quote="handleQuote"
          />
        </div>
        <div v-else class="flex flex-col items-center justify-center h-full text-muted-foreground">
          <FolderOpen class="w-12 h-12 mb-2 opacity-50" />
          <p class="text-sm">空文件夹</p>
        </div>
      </div>

      <DrawioEmbedRenderer v-else-if="drawioXmlContent" :xml="drawioXmlContent" />

      <!-- PDF 预览 -->
      <PdfRenderer v-else-if="fileType === 'pdf'" :file-path="filePath" @open-file="openFile" />

      <!-- 图片预览 -->
      <ImageRenderer v-else-if="fileType === 'image'" :file-path="filePath" :file-name="displayFileName" />

      <!-- 视频预览 -->
      <VideoRenderer v-else-if="fileType === 'video'" :file-path="filePath" :file-name="displayFileName" />

      <!-- 音频预览 -->
      <AudioRenderer v-else-if="fileType === 'audio'" :file-path="filePath" :file-name="displayFileName" />

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
      <DocxRenderer v-else-if="fileType === 'office' && (fileExtension === 'docx' || fileExtension === 'doc')" :file-path="filePath" :file-content="fileContent" />
      <XlsxRenderer v-else-if="fileType === 'office' && (fileExtension === 'xlsx' || fileExtension === 'xls')" :file-path="filePath" :file-content="fileContent" />
      <PptxRenderer v-else-if="fileType === 'office' && (fileExtension === 'pptx' || fileExtension === 'ppt')" :file-path="filePath" />
      <div v-else-if="fileType === 'office'" class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <FileText class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">{{ officeFileType }} 文件</p>
        <p class="text-xs text-muted-foreground/60 mb-4">此格式暂不支持预览</p>
        <Button variant="outline" size="sm" @click="openFile">
          <ExternalLink class="w-4 h-4 mr-1" />
          打开文件
        </Button>
      </div>

      <!-- 其他文件 -->
      <div v-else class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <File class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">此文件类型暂不支持预览</p>
        <p class="text-xs text-muted-foreground/60 mb-4">displayFileName: {{ displayFileName }}</p>
        <p class="text-xs text-muted-foreground/40">type: {{ fileType }}, ext: '{{ fileExtension }}'</p>
        <p class="text-xs text-muted-foreground/40">path: {{ filePath?.substring(0, 50) }}</p>
        <p class="text-xs text-muted-foreground/40">name prop: '{{ fileName }}'</p>
        <Button 
          variant="outline" 
          size="sm"
          @click="openFile"
        >
          <ExternalLink class="w-4 h-4 mr-1" />
          打开文件
        </Button>
      </div>
    </div>
  </div>

  <Dialog v-if="!dialogMode" v-model:open="previewDialogOpen">
    <DialogContent class="max-w-[90vw] h-[85vh] p-0 overflow-hidden">
      <FileRenderer
        :file-path="filePath"
        :file-name="fileName"
        :item="item"
        :refresh-version="refreshVersion"
        :dialog-mode="true"
        @download-file="$emit('downloadFile', $event)"
        @delete-file="$emit('deleteFile', $event)"
        @quote-path="$emit('quotePath', $event)"
      />
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { useLanguage } from '@/utils/i18n.js'
import {
  ExternalLink,
  Loader2,
  AlertCircle,
  RefreshCw,
  Copy,
  Check,
  File,
  Globe,
  FileText,
  Image as ImageIcon,
  Download,
  FolderOpen,
  Eye
} from 'lucide-vue-next'
import { open } from '@tauri-apps/plugin-shell'
import { readTextFile, readFile, exists, readDir } from '@tauri-apps/plugin-fs'
import { save } from '@tauri-apps/plugin-dialog'
import { toast } from 'vue-sonner'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useThemeStore } from '@/stores/theme'
import * as XLSX from 'xlsx'
import mammoth from 'mammoth'
import JSZip from 'jszip'
import { init as initPptxPreview } from 'pptx-preview'
import ExcalidrawRenderer from './filerender/ExcalidrawRenderer.vue'
import PdfRenderer from './filerender/PdfRenderer.vue'
import ImageRenderer from './filerender/ImageRenderer.vue'
import VideoRenderer from './filerender/VideoRenderer.vue'
import AudioRenderer from './filerender/AudioRenderer.vue'
import HtmlRenderer from './filerender/HtmlRenderer.vue'
import MarkdownRenderer from './filerender/MarkdownRenderer.vue'
import CodeRenderer from './filerender/CodeRenderer.vue'
import TextRenderer from './filerender/TextRenderer.vue'
import DocxRenderer from './filerender/DocxRenderer.vue'
import XlsxRenderer from './filerender/XlsxRenderer.vue'
import PptxRenderer from './filerender/PptxRenderer.vue'
import DrawioEmbedRenderer from './filerender/DrawioEmbedRenderer.vue'
import WorkspaceFileTree from '../../WorkspaceFileTree.vue'
import {
  buildDrawioPreviewUrlFromArrayBuffer,
  buildDrawioPreviewUrlFromText,
  isDirectDrawioExtension,
  isPotentialDrawioExtension
} from './filerender/drawio'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  fileName: {
    type: String,
    default: ''
  },
  item: {
    type: Object,
    default: () => ({})
  },
  refreshVersion: {
    type: Number,
    default: 0
  },
  dialogMode: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['downloadFile', 'deleteFile', 'quotePath'])
const { t } = useLanguage()

// 状态
const loading = ref(false)
const error = ref(null)
const fileContent = ref('')
const copied = ref(false)
const previewDialogOpen = ref(false)
const htmlDataUrl = ref('')
const isDirectory = ref(false)
const directoryTree = ref([])

// Office 文件状态
const officeLoading = ref(false)
const officeError = ref('')
const officeContent = ref(null)

// PPT 预览状态
const pptxLoading = ref(false)
const pptxError = ref('')
const pptxContainer = ref(null)
const pptxFileData = ref(null) // 存储 PPT 文件数据用于重新渲染

// 主题
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)

// 生成 HTML Data URL
const generateHtmlDataUrl = (content) => {
  console.log('[FileRenderer] generateHtmlDataUrl called, content length:', content?.length)
  if (!content) {
    console.log('[FileRenderer] No content provided')
    return ''
  }
  // 将 HTML 内容转换为 Blob，然后生成 Data URL
  const blob = new Blob([content], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  console.log('[FileRenderer] Data URL created:', url?.substring(0, 50))
  return url
}

// 刷新 HTML 预览
const refreshHtmlPreview = () => {
  if (htmlDataUrl.value) {
    URL.revokeObjectURL(htmlDataUrl.value)
  }
  htmlDataUrl.value = generateHtmlDataUrl(fileContent.value)
}

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': 'AI',
    'user': '用户',
    'system': '系统',
    'tool': '工具'
  }
  return roleMap[props.item?.role] || 'AI'
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
  // 优先从 filePath 提取文件名，因为 fileName 可能是链接文本
  if (!props.filePath) {
    return props.fileName || '未命名文件'
  }
  let pathName = props.filePath.split('/').pop()
  // 移除查询参数（如 ?t=123）
  pathName = pathName.split('?')[0]
  // 如果 pathName 有扩展名，使用它；否则使用 fileName
  if (pathName && pathName.includes('.')) {
    return pathName
  }
  return props.fileName || pathName || 'file'
})

const fileExtension = computed(() => {
  const name = displayFileName.value
  const match = name.match(/\.([^.]+)$/)
  return match ? match[1].toLowerCase() : ''
})

// 文件类型检测
const fileType = computed(() => {
  const ext = fileExtension.value
  const typeMap = {
    'pdf': 'pdf',
    'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image', 'webp': 'image', 'svg': 'image',
    'mp4': 'video', 'webm': 'video', 'mov': 'video', 'mkv': 'video', 'avi': 'video', 'flv': 'video', 'm4v': 'video',
    'mp3': 'audio', 'wav': 'audio', 'ogg': 'audio', 'm4a': 'audio', 'aac': 'audio', 'flac': 'audio', 'wma': 'audio',
    'html': 'html', 'htm': 'html',
    'md': 'markdown', 'markdown': 'markdown',
    'excalidraw': 'excalidraw',
    'drawio': 'drawio', 'dio': 'drawio',
    'vsdx': 'drawio', 'vssx': 'drawio', 'vstx': 'drawio',
    'gliffy': 'drawio', 'lucid': 'drawio', 'lucidchart': 'drawio',
    'js': 'code', 'ts': 'code', 'jsx': 'code', 'tsx': 'code',
    'py': 'code', 'java': 'code', 'cpp': 'code', 'c': 'code', 'go': 'code', 'rs': 'code',
    'json': 'code', 'xml': 'code', 'yaml': 'code', 'yml': 'code',
    'css': 'code', 'scss': 'code', 'less': 'code',
    'vue': 'code', 'svelte': 'code',
    'php': 'code', 'rb': 'code', 'swift': 'code', 'kt': 'code',
    'sql': 'code', 'sh': 'code', 'bash': 'code', 'zsh': 'code',
    'txt': 'text', 'log': 'text', 'csv': 'text',
    'pptx': 'office', 'ppt': 'office',
    'docx': 'office', 'doc': 'office',
    'xlsx': 'office', 'xls': 'office'
  }
  return typeMap[ext] || 'other'
})

const fileTypeLabel = computed(() => {
  const labels = {
    'pdf': 'PDF',
    'image': '图片',
    'video': '视频',
    'audio': '音频',
    'html': 'HTML',
    'markdown': 'Markdown',
    'excalidraw': 'Excalidraw',
    'drawio': 'Draw.io',
    'code': '代码',
    'text': '文本',
    'office': officeFileType.value,
    'other': '文件'
  }
  return labels[fileType.value] || '文件'
})

// 文件图标
const fileIcon = computed(() => {
  const icons = {
    'pdf': '📕',
    'image': '🖼️',
    'video': '🎬',
    'audio': '🎵',
    'html': '🌐',
    'markdown': '📝',
    'excalidraw': '✏️',
    'drawio': '📊',
    'code': '📜',
    'text': '📃',
    'office': '📊',
    'other': '📎'
  }
  return icons[fileType.value] || '📎'
})

// 编程语言
const language = computed(() => {
  const langMap = {
    'js': 'JavaScript', 'ts': 'TypeScript', 
    'jsx': 'JSX', 'tsx': 'TSX',
    'py': 'Python', 'java': 'Java',
    'cpp': 'C++', 'c': 'C',
    'go': 'Go', 'rs': 'Rust',
    'json': 'JSON', 'xml': 'XML',
    'yaml': 'YAML', 'yml': 'YAML',
    'css': 'CSS', 'scss': 'SCSS', 'less': 'Less',
    'vue': 'Vue', 'svelte': 'Svelte',
    'php': 'PHP', 'rb': 'Ruby',
    'swift': 'Swift', 'kt': 'Kotlin',
    'sql': 'SQL', 'sh': 'Shell',
    'bash': 'Bash', 'zsh': 'Zsh'
  }
  return langMap[fileExtension.value] || fileExtension.value.toUpperCase()
})

// Office 文件类型名称
const officeFileType = computed(() => {
  const officeMap = {
    'pptx': 'PowerPoint', 'ppt': 'PowerPoint',
    'docx': 'Word', 'doc': 'Word',
    'xlsx': 'Excel', 'xls': 'Excel'
  }
  return officeMap[fileExtension.value] || 'Office'
})

// 是否可以复制
const canCopy = computed(() => {
  return ['code', 'text', 'markdown'].includes(fileType.value)
})

const canPreviewInDialog = computed(() => {
  if (props.dialogMode || isDirectory.value) return false
  return ['pdf', 'image', 'video', 'audio', 'html', 'markdown', 'code', 'excalidraw', 'drawio', 'text', 'office'].includes(fileType.value)
})

const drawioOpenUrl = ref('')
const drawioXmlContent = ref('')

const createDrawioPreviewUrl = ({ textContent = '', arrayBuffer = null } = {}) => {
  if (!isPotentialDrawioExtension(fileExtension.value)) return ''
  const direct = isDirectDrawioExtension(fileExtension.value)

  if (textContent) {
    return buildDrawioPreviewUrlFromText({
      content: textContent,
      fileName: displayFileName.value,
      extension: fileExtension.value,
      force: direct
    })
  }

  if (arrayBuffer) {
    return buildDrawioPreviewUrlFromArrayBuffer({
      arrayBuffer,
      fileName: displayFileName.value,
      extension: fileExtension.value,
      force: direct
    })
  }

  return ''
}

// 检查文件内容是否为二进制（例如 ZIP/PPTX 文件被错误标记为 .md）
const isBinaryContent = computed(() => {
  if (!fileContent.value) return false
  // 检查是否以 ZIP 文件头 (PK) 开头
  if (fileContent.value.startsWith('PK')) {
    return true
  }
  // 检查是否包含大量不可打印字符
  const sample = fileContent.value.slice(0, 100)
  const nonPrintable = sample.match(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g)
  if (nonPrintable && nonPrintable.length > 10) {
    return true
  }
  return false
})

// Markdown 渲染
const renderedMarkdown = computed(() => {
  if (fileType.value !== 'markdown' || !fileContent.value) return ''
  const html = marked(fileContent.value)
  return DOMPurify.sanitize(html)
})

// Excalidraw 特定数据
const excalidrawElementCount = ref(0)
const excalidrawTypeSummary = ref('')
const excalidrawWidth = ref(800)
const excalidrawHeight = ref(600)
const excalidrawSvg = ref('')
const excalidrawData = ref(null)

// 生成 Excalidraw SVG
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
      case 'diamond':
        const cx = x + w/2, cy = y + h/2
        svgElements += `<polygon points="${cx},${y} ${x + w},${cy} ${cx},${y + h} ${x},${cy}" ${style}/>`
        break
      case 'line':
      case 'arrow':
        if (el.points && el.points.length >= 2) {
          const pathD = el.points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x + p[0]} ${y + p[1]}`).join(' ')
          svgElements += `<path d="${pathD}" stroke="${stroke}" stroke-width="${strokeWidth}" fill="none" opacity="${opacity}"/>`
        }
        break
      case 'text':
        if (el.text) {
          const text = el.text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/&/g, '&amp;')
          const fontSize = el.fontSize || 20
          const fontFamily = el.fontFamily === 1 ? 'Courier New' : el.fontFamily === 2 ? 'Georgia' : 'system-ui'
          svgElements += `<text x="${x}" y="${y + fontSize}" font-size="${fontSize}" font-family="${fontFamily}" fill="${stroke}" opacity="${opacity}">${text.substring(0, 100)}</text>`
        }
        break
      case 'freedraw':
        if (el.points && el.points.length > 1) {
          const pathD = el.points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x + p[0]} ${y + p[1]}`).join(' ')
          svgElements += `<path d="${pathD}" stroke="${stroke}" stroke-width="${strokeWidth}" fill="none" opacity="${opacity}" stroke-linecap="round" stroke-linejoin="round"/>`
        }
        break
    }
  })
  
  return svgElements
}

// 加载文件夹内容
const loadDirectory = async () => {
  try {
    loading.value = true
    error.value = null
    
    const entries = await readDir(props.filePath)
    
    // 构建文件树
    const buildTree = async (entries, basePath) => {
      const nodes = []
      
      for (const entry of entries) {
        const fullPath = `${basePath}/${entry.name}`
        const node = {
          name: entry.name,
          path: fullPath,
          is_directory: entry.isDirectory,
          size: 0,
          children: []
        }
        
        if (entry.isDirectory) {
          try {
            const childEntries = await readDir(fullPath)
            node.children = await buildTree(childEntries, fullPath)
          } catch (e) {
            console.warn('Failed to read directory:', fullPath, e)
          }
        }
        
        nodes.push(node)
      }
      
      // 排序：文件夹在前，按名称排序
      nodes.sort((a, b) => {
        if (a.is_directory !== b.is_directory) {
          return a.is_directory ? -1 : 1
        }
        return a.name.localeCompare(b.name)
      })
      
      return nodes
    }
    
    directoryTree.value = await buildTree(entries, props.filePath)
    loading.value = false
  } catch (err) {
    console.error('加载文件夹失败:', err)
    error.value = `加载文件夹失败: ${err.message}`
    loading.value = false
  }
}

// 加载文件内容
const loadContent = async () => {
  // 检查文件路径是否存在
  if (!props.filePath) {
    error.value = '未指定文件路径'
    return
  }

  // 首先检查是否是文件夹
  try {
    const dirExists = await exists(props.filePath)
    if (!dirExists) {
      error.value = '路径不存在'
      return
    }
    
    // 尝试读取文件夹
    try {
      const entries = await readDir(props.filePath)
      isDirectory.value = true
      await loadDirectory()
      return
    } catch (e) {
      // 不是文件夹，继续按文件处理
      isDirectory.value = false
    }
  } catch (err) {
    console.error('检查路径失败:', err)
  }
  
  if (fileType.value === 'other') return
  
  try {
    loading.value = true
    error.value = null
    drawioOpenUrl.value = ''
    drawioXmlContent.value = ''
    
    if (['pdf', 'image', 'video', 'audio'].includes(fileType.value) && !isPotentialDrawioExtension(fileExtension.value)) {
      loading.value = false
      return
    }
    
    // Office 文件使用二进制读取，其他使用文本读取
    if (fileType.value === 'office') {
      // 读取二进制文件并转换为 base64
      const fileData = await readFile(props.filePath)
      const base64 = btoa(String.fromCharCode(...new Uint8Array(fileData)))
      fileContent.value = base64
    } else {
      const shouldTryBinaryForDrawio = isPotentialDrawioExtension(fileExtension.value)
      let fileArrayBufferValue = null

      if (shouldTryBinaryForDrawio) {
        const fileData = await readFile(props.filePath)
        fileArrayBufferValue = new Uint8Array(fileData).buffer
        drawioOpenUrl.value = createDrawioPreviewUrl({ arrayBuffer: fileArrayBufferValue })
      }

      if (!drawioOpenUrl.value || fileType.value === 'drawio' || ['html', 'markdown', 'code', 'text'].includes(fileType.value)) {
        fileContent.value = await readTextFile(props.filePath)
        if (!drawioOpenUrl.value) {
          drawioOpenUrl.value = createDrawioPreviewUrl({ textContent: fileContent.value })
        }
        if (
          (fileType.value === 'drawio' || fileExtension.value === 'xml') &&
          fileContent.value &&
          fileContent.value.includes('<mxfile')
        ) {
          drawioXmlContent.value = fileContent.value
        }
      }

      if (drawioXmlContent.value || fileType.value === 'drawio') {
        loading.value = false
        return
      }
    }

    if (fileType.value === 'excalidraw') {
      try {
        const data = JSON.parse(fileContent.value)
        excalidrawElementCount.value = data.elements?.length || 0

        const typeCount = {}
        data.elements?.forEach(el => {
          typeCount[el.type] = (typeCount[el.type] || 0) + 1
        })
        excalidrawTypeSummary.value = Object.entries(typeCount)
          .map(([type, count]) => `${type}: ${count}`)
          .join(', ')

        // 设置 Excalidraw 数据用于组件渲染
        // 限制画布尺寸以避免浏览器限制 (最大 8000 x 8000 = 64000000 像素)
        const maxCanvasSize = 4000
        const contentWidth = excalidrawWidth.value
        const contentHeight = excalidrawHeight.value
        const scale = Math.min(1, maxCanvasSize / Math.max(contentWidth, contentHeight))
        
        excalidrawData.value = {
          elements: data.elements || [],
          appState: {
            ...data.appState,
            viewBackgroundColor: data.appState?.viewBackgroundColor || '#ffffff',
            // 限制画布尺寸
            width: Math.min(contentWidth, maxCanvasSize),
            height: Math.min(contentHeight, maxCanvasSize),
            // 设置缩放以适应内容
            zoom: { value: scale }
          },
          files: data.files || {}
        }

        // 同时生成 SVG 作为备用
        excalidrawSvg.value = generateExcalidrawSvg(data)
      } catch (e) {
        console.warn('解析 Excalidraw 数据失败:', e)
      }
    } else if (fileType.value === 'html') {
      // 生成 HTML Data URL 用于预览
      console.log('[FileRenderer] Generating HTML Data URL, fileContent length:', fileContent.value?.length)
      htmlDataUrl.value = generateHtmlDataUrl(fileContent.value)
      console.log('[FileRenderer] HTML Data URL generated:', htmlDataUrl.value?.substring(0, 50))
    }

    loading.value = false
  } catch (err) {
    console.error('加载文件失败:', err)
    error.value = `加载失败: ${err.message}`
    loading.value = false
  }
}

// 打开文件
const openFile = async () => {
  try {
    if (fileType.value === 'pdf') {
      const pdfCheck = await quickValidatePdf(filePath.value)
      if (!pdfCheck.ok) {
        toast.error(
          t('workbench.pdf.toastCorrupt', {
            name: displayFileName.value,
            reason: pdfCheck.reason
          })
        )
        return
      }
    }
    await open(props.filePath)
  } catch (err) {
    console.error('打开文件失败:', err)
    if (fileType.value === 'pdf') {
      toast.error(
        t('workbench.pdf.toastOpenFailed', { name: displayFileName.value })
      )
      return
    }
    toast.error(t('workbench.file.openFailed', { message: err?.message || 'Unknown' }))
  }
}

const quickValidatePdf = async (path) => {
  try {
    const fileData = await readFile(path)
    if (!fileData || fileData.length < 8) {
      return { ok: false, reason: t('workbench.pdf.checkEmpty') }
    }

    const u8 = new Uint8Array(fileData)
    const decoder = new TextDecoder('ascii')
    const header = decoder.decode(u8.slice(0, Math.min(8, u8.length)))
    if (!header.startsWith('%PDF-')) {
      return { ok: false, reason: t('workbench.pdf.checkInvalidHeader') }
    }

    // 允许尾部有空白，检查末尾 2KB 是否包含 EOF 标记。
    const tailBytes = u8.slice(Math.max(0, u8.length - 2048))
    const tail = decoder.decode(tailBytes)
    if (!tail.includes('%%EOF')) {
      return { ok: false, reason: t('workbench.pdf.checkMissingEof') }
    }

    return { ok: true, reason: '' }
  } catch (err) {
    return { ok: false, reason: err?.message || t('workbench.pdf.checkReadFailed') }
  }
}

// 下载文件
const downloadFile = async () => {
  try {
    // 读取文件内容
    const fileData = await readFile(props.filePath)
    console.log('[FileRenderer] Download file, size:', fileData.length, 'name:', displayFileName.value)

    // 提取文件扩展名
    const fileName = displayFileName.value
    const extMatch = fileName.match(/\.([^.]+)$/)
    const ext = extMatch ? extMatch[1] : ''

    // 弹出保存对话框
    const savePath = await save({
      defaultPath: fileName,
      filters: ext ? [{
        name: `${ext.toUpperCase()} 文件`,
        extensions: [ext]
      }] : undefined
    })

    if (savePath) {
      console.log('[FileRenderer] Saving to:', savePath)
      // 写入文件 - 使用 Uint8Array 直接写入
      const { writeFile } = await import('@tauri-apps/plugin-fs')
      await writeFile(savePath, fileData)
      toast.success(`已保存到: ${savePath}`)
    }
  } catch (error) {
    console.error('[FileRenderer] 下载文件失败:', error)
    toast.error('下载失败: ' + error.message)
  }
}

// 在 Excalidraw 打开
const openInExcalidraw = () => {
  window.open('https://excalidraw.com', '_blank')
}

const openInDrawio = async () => {
  if (!drawioOpenUrl.value) return
  try {
    await open(drawioOpenUrl.value)
  } catch (error) {
    console.error('在 draw.io 中打开失败:', error)
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

// ============ Office 文件解析 ============

// 解析 DOCX 文件
const parseDocx = async (filePath) => {
  try {
    // 读取文件为二进制
    const fileData = await readFile(filePath)
    const arrayBuffer = new Uint8Array(fileData).buffer

    // 使用 mammoth 解析
    const result = await mammoth.convertToHtml({ arrayBuffer })
    return result.value
  } catch (error) {
    console.error('解析 DOCX 失败:', error)
    throw new Error('无法解析 Word 文档')
  }
}

// 解析 XLSX 文件
const parseXlsx = async (filePath) => {
  try {
    // 读取文件为二进制
    const fileData = await readFile(filePath)
    const arrayBuffer = new Uint8Array(fileData).buffer

    // 使用 xlsx 解析
    const workbook = XLSX.read(arrayBuffer, { type: 'array' })

    // 读取所有工作表
    const sheets = {}
    workbook.SheetNames.forEach(sheetName => {
      const worksheet = workbook.Sheets[sheetName]
      // 转换为 JSON 数组
      const jsonData = XLSX.utils.sheet_to_json(worksheet, { header: 1 })
      sheets[sheetName] = jsonData
    })

    return sheets
  } catch (error) {
    console.error('解析 XLSX 失败:', error)
    throw new Error('无法解析 Excel 表格')
  }
}

// 解析 PPTX 文件
const parsePptx = async (filePath) => {
  try {
    console.log('[FileRenderer] Starting PPTX parse:', filePath)

    // 读取文件为二进制
    const fileData = await readFile(filePath)
    console.log('[FileRenderer] File data length:', fileData.length)

    const arrayBuffer = new Uint8Array(fileData).buffer

    // 使用 JSZip 解压 PPTX 文件
    const zip = await JSZip.loadAsync(arrayBuffer)
    console.log('[FileRenderer] ZIP loaded, files:', Object.keys(zip.files).slice(0, 10))

    // 获取演示文稿内容
    const slides = []

    // 获取幻灯片列表（从 presentation.xml）
    const presentationXml = await zip.file('ppt/presentation.xml')?.async('text')
    console.log('[FileRenderer] presentation.xml exists:', !!presentationXml)

    if (!presentationXml) {
      // 尝试列出所有文件
      const allFiles = Object.keys(zip.files)
      console.log('[FileRenderer] All files in ZIP:', allFiles)
      throw new Error('无法读取演示文稿结构，找不到 ppt/presentation.xml')
    }

    // 解析幻灯片列表 - 使用更精确的正则
    // PPTX 中幻灯片引用格式为: <p:sldId id="256" r:id="rId2"/>
    // 我们需要从 rId 映射到实际的 slide 文件名
    const slideIdRegex = /<p:sldId[^>]*r:id="rId(\d+)"[^>]*\/>/g
    const slideIds = []
    let match
    while ((match = slideIdRegex.exec(presentationXml)) !== null) {
      slideIds.push(parseInt(match[1]))
    }
    console.log('[FileRenderer] Found slide IDs:', slideIds)

    // 获取关系映射 (从 _rels/presentation.xml.rels)
    const relsXml = await zip.file('ppt/_rels/presentation.xml.rels')?.async('text')
    console.log('[FileRenderer] rels.xml exists:', !!relsXml)

    const slideRels = {}
    if (relsXml) {
      const relRegex = /<Relationship[^>]*Id="rId(\d+)"[^>]*Target="([^"]*)"[^>]*\/>/g
      while ((match = relRegex.exec(relsXml)) !== null) {
        slideRels[match[1]] = match[2]
      }
    }
    console.log('[FileRenderer] Slide relationships:', slideRels)

    // 逐个解析幻灯片
    for (let i = 0; i < slideIds.length; i++) {
      const rId = slideIds[i]
      const slideFileName = slideRels[rId]

      if (slideFileName) {
        const fullPath = 'ppt/' + slideFileName
        console.log(`[FileRenderer] Loading slide ${i + 1} from:`, fullPath)

        const slideXml = await zip.file(fullPath)?.async('text')

        if (slideXml) {
          console.log(`[FileRenderer] Slide ${i + 1} XML length:`, slideXml.length)
          const slideData = parseSlideXml(slideXml, i + 1)
          console.log(`[FileRenderer] Slide ${i + 1} parsed:`, slideData)
          slides.push(slideData)
        } else {
          console.warn(`[FileRenderer] Slide ${i + 1} not found at:`, fullPath)
        }
      }
    }

    console.log('[FileRenderer] Total slides parsed:', slides.length)

    if (slides.length === 0) {
      return [{ number: 1, title: '无法解析', content: ['无法提取 PPTX 内容'] }]
    }

    return slides
  } catch (error) {
    console.error('[FileRenderer] 解析 PPTX 失败:', error)
    throw new Error('无法解析 PowerPoint 演示文稿: ' + error.message)
  }
}

// 解析单个幻灯片 XML
const parseSlideXml = (xml, slideNumber) => {
  const slideData = {
    number: slideNumber,
    title: '',
    content: [],
    layout: 'title_and_content' // 默认布局
  }

  // 提取标题（通常是第一个较大的文本）
  // PPTX 中标题通常在 <p:ph type="title" 或 <p:ph type="ctrTitle"> 中
  const titleMatch = xml.match(/<p:ph[^>]*type="(?:title|ctrTitle)"[^>]*>.*?<a:t>([^<]*)<\/a:t>/s)
  if (titleMatch) {
    slideData.title = titleMatch[1].trim()
  }

  // 提取所有文本内容
  // 匹配所有 <a:t> 标签中的文本
  const textMatches = xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)
  const texts = []
  for (const match of textMatches) {
    const text = match[1].trim()
    if (text && !texts.includes(text)) {
      texts.push(text)
    }
  }

  // 如果第一个文本是标题，从内容中移除
  if (texts.length > 0 && texts[0] === slideData.title) {
    texts.shift()
  }

  // 识别布局类型
  if (xml.includes('type="title"') && xml.includes('type="body"')) {
    slideData.layout = 'title_and_content'
  } else if (xml.includes('type="title"') && !xml.includes('type="body"')) {
    slideData.layout = 'title_only'
  } else if (!slideData.title && texts.length > 0) {
    slideData.layout = 'content_only'
  }

  // 组织内容
  // 将文本按段落分组
  slideData.content = texts

  // 如果没有标题但有内容，使用第一行作为标题
  if (!slideData.title && slideData.content.length > 0) {
    slideData.title = slideData.content[0]
    slideData.content = slideData.content.slice(1)
  }

  return slideData
}

// 加载 Office 文件内容
const loadOfficeContent = async () => {
  if (fileType.value !== 'office') return

  const ext = fileExtension.value

  // PPT 文件现在由 PptxRenderer 组件处理，这里不需要处理
  if (ext === 'pptx' || ext === 'ppt') {
    return
  }

  // DOCX 和 XLSX 现在由各自的组件处理，这里不需要处理
  if (ext === 'docx' || ext === 'doc' || ext === 'xlsx' || ext === 'xls') {
    return
  }

  // 其他 Office 格式显示错误
  officeLoading.value = false
  officeError.value = '不支持的 Office 格式'
}

// 使用 pptx-preview 加载 PPT
const loadPptxPreview = async (retryCount = 0) => {
  const maxRetries = 3

  // 检查容器是否存在
  if (!pptxContainer.value) {
    if (retryCount < maxRetries) {
      console.log(`[FileRenderer] PPTX container not ready, retrying... (${retryCount + 1}/${maxRetries})`)
      setTimeout(() => loadPptxPreview(retryCount + 1), 100)
      return
    }
    console.warn('[FileRenderer] PPTX container not ready after retries')
    pptxError.value = '预览容器未准备好'
    return
  }

  pptxLoading.value = true
  pptxError.value = ''

  try {
    console.log('[FileRenderer] Loading PPTX with pptx-preview:', props.filePath)
    console.log('[FileRenderer] Container element:', pptxContainer.value)
    console.log('[FileRenderer] Container dimensions:', {
      width: pptxContainer.value?.offsetWidth,
      height: pptxContainer.value?.offsetHeight,
      clientWidth: pptxContainer.value?.clientWidth,
      clientHeight: pptxContainer.value?.clientHeight
    })

    // 读取文件为二进制
    const fileData = await readFile(props.filePath)
    console.log('[FileRenderer] File data loaded, size:', fileData.length)

    // 存储文件数据用于重新渲染
    pptxFileData.value = fileData

    await renderPptxWithSize(fileData)
  } catch (error) {
    console.error('[FileRenderer] Failed to render PPTX:', error)
    pptxError.value = '无法渲染 PowerPoint 文件: ' + error.message
  } finally {
    pptxLoading.value = false
  }
}

// 渲染 PPT 根据当前容器尺寸
const renderPptxWithSize = async (fileData) => {
  if (!pptxContainer.value || !fileData) return

  const arrayBuffer = new Uint8Array(fileData).buffer

  // 确保容器可见且有尺寸
  pptxContainer.value.style.width = '100%'
  pptxContainer.value.style.height = '100%'
  pptxContainer.value.style.minHeight = '400px'

  // 获取容器实际尺寸
  const containerWidth = pptxContainer.value?.clientWidth || 800
  const containerHeight = pptxContainer.value?.clientHeight || 600

  // 使用容器全尺寸，不留边距
  const width = containerWidth
  const height = containerHeight

  console.log('[FileRenderer] Container dimensions:', { containerWidth, containerHeight })

  // 清空容器
  pptxContainer.value.innerHTML = ''

  // 初始化 pptx-preview
  console.log('[FileRenderer] Initializing pptx-preview...')
  const pptxPreviewer = initPptxPreview(pptxContainer.value, {
    width: Math.floor(width),
    height: Math.floor(height),
    mode: 'list' // 使用 list 模式，支持上下滚动
  })
  console.log('[FileRenderer] Previewer initialized:', pptxPreviewer)

  // 调用预览方法
  console.log('[FileRenderer] Calling preview method...')
  await pptxPreviewer.preview(arrayBuffer)

  console.log('[FileRenderer] PPTX rendered successfully')
}

// 处理窗口大小变化
let resizeTimeout = null
const handleResize = () => {
  if (fileType.value !== 'office' || (fileExtension.value !== 'pptx' && fileExtension.value !== 'ppt')) return
  if (!pptxFileData.value) return

  // 防抖处理
  clearTimeout(resizeTimeout)
  resizeTimeout = setTimeout(() => {
    console.log('[FileRenderer] Window resized, re-rendering PPTX...')
    renderPptxWithSize(pptxFileData.value)
  }, 300)
}

// 文件夹操作处理
const handleDownload = (item) => {
  emit('downloadFile', item)
}

const handleDelete = (item) => {
  emit('deleteFile', item)
}

const handleQuote = (path) => {
  emit('quotePath', path)
}

// 自动加载
onMounted(() => {
  loadContent()
  // 如果是 Office 文件，额外加载 Office 内容
  if (fileType.value === 'office') {
    loadOfficeContent()
  }

  // 监听窗口大小变化
  window.addEventListener('resize', handleResize)
})

// 监听文件路径变化，重新加载内容
watch(() => props.filePath, (newPath, oldPath) => {
  if (newPath && newPath !== oldPath) {
    console.log('[FileRenderer] File path changed from', oldPath, 'to', newPath)
    loadContent()
    // 如果是 Office 文件，额外加载 Office 内容
    if (fileType.value === 'office') {
      loadOfficeContent()
    }
  }
})

// 监听刷新版本：同一路径文件内容更新时强制重新加载
watch(() => props.refreshVersion, (newVersion, oldVersion) => {
  if (newVersion !== oldVersion && props.filePath) {
    console.log('[FileRenderer] Refresh version changed from', oldVersion, 'to', newVersion)
    loadContent()
    if (fileType.value === 'office') {
      loadOfficeContent()
    }
  }
})

// 清理
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  clearTimeout(resizeTimeout)
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

.markdown-preview :deep(pre) {
  background-color: hsl(var(--muted));
  padding: 0.75rem;
  border-radius: 0.375rem;
  overflow-x: auto;
}

.markdown-preview :deep(code) {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.875em;
}

.markdown-preview :deep(p) {
  margin-bottom: 0.75rem;
}

.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin-left: 1.5rem;
  margin-bottom: 0.75rem;
}

/* Excalidraw SVG 样式 */
.excalidraw-preview svg {
  background-color: rgba(255, 255, 255, 0.8);
}

.code-preview pre,
.text-preview pre {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.875rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* PPTX 预览样式 - 移除边距 */
.pptx-preview-container :deep(*) {
  margin: 0 !important;
  padding: 0 !important;
}

.pptx-preview-container :deep(.pptx-preview) {
  width: 100% !important;
  height: 100% !important;
}

.pptx-preview-container :deep(.pptx-slide) {
  margin: 0 !important;
  padding: 0 !important;
}
</style>
