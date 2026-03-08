<template>
  <div class="file-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合后的头部：包含 ItemHeader 信息和文件操作 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <!-- ItemHeader 信息 -->
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <!-- 文件信息 -->
        <span class="text-xl">{{ fileIcon }}</span>
        <span class="text-sm font-medium truncate">{{ displayFileName }}</span>
        <Badge variant="secondary" class="text-xs">{{ fileTypeLabel }}</Badge>
      </div>
      <div class="flex items-center gap-1 flex-shrink-0">
        <Button 
          v-if="canCopy"
          variant="ghost" 
          size="sm"
          @click="copyContent"
          class="h-7 px-2"
        >
          <Copy v-if="!copied" class="w-4 h-4 mr-1" />
          <Check v-else class="w-4 h-4 mr-1 text-green-500" />
          {{ copied ? '已复制' : '复制' }}
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          @click="openFile"
          class="h-7 px-2"
          title="打开文件"
        >
          <ExternalLink class="w-4 h-4 mr-1" />
          打开
        </Button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 overflow-auto">
      <!-- 加载中 -->
      <div v-if="loading" class="flex items-center justify-center h-full">
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

      <!-- PDF 预览 -->
      <div v-else-if="fileType === 'pdf'" class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <FileText class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">PDF 文件</p>
        <p class="text-xs text-muted-foreground/60 mb-4">由于浏览器安全限制，无法直接预览本地 PDF</p>
        <Button 
          variant="outline" 
          size="sm"
          @click="openFile"
        >
          <ExternalLink class="w-4 h-4 mr-1" />
          打开 PDF
        </Button>
      </div>

      <!-- 图片预览 -->
      <div v-else-if="fileType === 'image'" class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
        <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">图片文件</p>
        <p class="text-xs text-muted-foreground/60 mb-4">{{ displayFileName }}</p>
        <Button 
          variant="outline" 
          size="sm"
          @click="openFile"
        >
          <ExternalLink class="w-4 h-4 mr-1" />
          打开图片
        </Button>
      </div>

      <!-- HTML 预览 -->
      <div v-else-if="fileType === 'html'" class="h-full flex flex-col">
        <!-- HTML 工具栏 -->
        <div class="flex items-center justify-between px-3 py-2 bg-muted/30 border-b border-border flex-none">
          <div class="flex items-center gap-2 text-xs text-muted-foreground">
            <Globe class="w-3 h-3" />
            <span>HTML 预览</span>
          </div>
          <div class="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              class="h-7 px-2 text-xs"
              @click="refreshHtmlPreview"
            >
              <RefreshCw class="w-3 h-3 mr-1" />
              刷新
            </Button>
            <Button
              variant="ghost"
              size="sm"
              class="h-7 px-2 text-xs"
              @click="openFile"
            >
              <ExternalLink class="w-3 h-3 mr-1" />
              外部打开
            </Button>
          </div>
        </div>
        <!-- HTML iframe 渲染 -->
        <div class="flex-1 relative bg-white">
          <iframe
            v-if="htmlDataUrl"
            :src="htmlDataUrl"
            class="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
            title="HTML Preview"
          ></iframe>
          <div v-else class="h-full flex items-center justify-center text-muted-foreground">
            <div class="text-center">
              <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
              <p class="text-sm">加载中...</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Markdown 预览 -->
      <div v-else-if="fileType === 'markdown'" class="markdown-preview p-4">
        <!-- 如果内容看起来是二进制文件，显示错误 -->
        <div v-if="isBinaryContent" class="flex flex-col items-center justify-center h-full text-muted-foreground">
          <FileText class="w-16 h-16 mb-3 opacity-50" />
          <p class="text-sm mb-1">文件内容异常</p>
          <p class="text-xs text-destructive mb-4">该文件可能不是有效的 Markdown 文件</p>
          <Button variant="outline" size="sm" @click="openFile">
            <ExternalLink class="w-4 h-4 mr-1" />
            打开文件
          </Button>
        </div>
        <div v-else class="prose prose-sm max-w-none dark:prose-invert" v-html="renderedMarkdown"></div>
      </div>

      <!-- 代码文件预览 -->
      <div v-else-if="fileType === 'code'" class="code-preview h-full">
        <div class="flex items-center justify-between px-3 py-2 bg-muted/50 border-b text-xs sticky top-0">
          <span class="text-muted-foreground">{{ language }}</span>
        </div>
        <pre class="p-4 text-sm overflow-auto"><code>{{ fileContent }}</code></pre>
      </div>

      <!-- Excalidraw 预览 -->
      <div v-else-if="fileType === 'excalidraw'" class="excalidraw-preview h-full overflow-auto" :style="{ backgroundColor: excalidrawBgColor }">
        <div class="p-4">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2 text-xs" :class="isDark ? 'text-gray-400' : 'text-muted-foreground'">
              <span>{{ excalidrawElementCount }} 个元素</span>
              <span v-if="excalidrawTypeSummary" class="opacity-50">|</span>
              <span v-if="excalidrawTypeSummary" class="truncate max-w-[200px]" :title="excalidrawTypeSummary">{{ excalidrawTypeSummary }}</span>
            </div>
            <Button
              variant="outline"
              size="sm"
              @click="openInExcalidraw"
            >
              <ExternalLink class="w-3 h-3 mr-1" />
              在 Excalidraw 打开
            </Button>
          </div>
          <!-- SVG 预览 -->
          <div class="overflow-auto border rounded" :class="isDark ? 'border-gray-700 bg-gray-800/50' : 'border-border/30 bg-white/80'">
            <svg
              :viewBox="`0 0 ${excalidrawWidth + 100} ${excalidrawHeight + 100}`"
              class="w-full h-auto"
              style="min-height: 200px;"
              v-html="excalidrawSvg"
            ></svg>
          </div>
          <div v-if="excalidrawElementCount > 100" class="mt-2 text-[10px] text-center" :class="isDark ? 'text-gray-500' : 'text-muted-foreground/60'">
            仅显示前 100 个元素
          </div>
        </div>
      </div>

      <!-- 文本文件预览 -->
      <div v-else-if="fileType === 'text'" class="text-preview h-full">
        <pre class="p-4 text-sm overflow-auto"><code>{{ fileContent }}</code></pre>
      </div>

      <!-- Office 文件预览 -->
      <div v-else-if="fileType === 'office'" class="office-preview h-full overflow-auto p-4">
        <!-- 加载中 -->
        <div v-if="officeLoading" class="flex items-center justify-center h-full text-muted-foreground">
          <div class="text-center">
            <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
            <p class="text-sm">正在解析 {{ officeFileType }} 文件...</p>
          </div>
        </div>
        <!-- 错误提示 -->
        <div v-else-if="officeError" class="flex flex-col items-center justify-center h-full text-muted-foreground">
          <FileText class="w-16 h-16 mb-3 opacity-50" />
          <p class="text-sm mb-1">{{ officeFileType }} 文件</p>
          <p class="text-xs text-destructive mb-4">{{ officeError }}</p>
          <Button variant="outline" size="sm" @click="openFile">
            <ExternalLink class="w-4 h-4 mr-1" />
            打开文件
          </Button>
        </div>
        <!-- DOCX 内容 -->
        <div v-else-if="fileExtension === 'docx' || fileExtension === 'doc'" class="docx-content prose prose-sm dark:prose-invert max-w-none">
          <div v-html="officeContent"></div>
        </div>
        <!-- XLSX 内容 -->
        <div v-else-if="fileExtension === 'xlsx' || fileExtension === 'xls'" class="xlsx-content">
          <div v-for="(sheet, sheetName) in officeContent" :key="sheetName" class="mb-6">
            <h3 class="text-sm font-medium mb-2 text-muted-foreground">{{ sheetName }}</h3>
            <div class="overflow-x-auto">
              <table class="w-full text-sm border-collapse border border-border">
                <tbody>
                  <tr v-for="(row, rowIndex) in sheet" :key="rowIndex" class="border-b border-border">
                    <td v-for="(cell, cellIndex) in row" :key="cellIndex" class="px-3 py-2 border-r border-border min-w-[80px]">
                      {{ cell }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <!-- PPTX 内容 - 使用 pptx-preview -->
        <div v-else-if="fileExtension === 'pptx' || fileExtension === 'ppt'" class="pptx-content h-full flex flex-col">
          <!-- 加载中 -->
          <div v-show="pptxLoading" class="flex items-center justify-center h-full text-muted-foreground">
            <div class="text-center">
              <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
              <p class="text-sm">正在加载 PPT...</p>
            </div>
          </div>
          <!-- 错误提示 -->
          <div v-show="!pptxLoading && pptxError" class="flex flex-col items-center justify-center h-full text-muted-foreground">
            <FileText class="w-16 h-16 mb-3 opacity-50" />
            <p class="text-sm mb-1">PowerPoint 文件</p>
            <p class="text-xs text-destructive mb-4">{{ pptxError }}</p>
            <Button variant="outline" size="sm" @click="openFile">
              <ExternalLink class="w-4 h-4 mr-1" />
              打开文件
            </Button>
          </div>
          <!-- PPT 预览容器 - 始终存在，使用 v-show 控制显示 -->
          <div ref="pptxContainer" v-show="!pptxLoading && !pptxError" class="pptx-preview-container flex-1 overflow-auto">
            <!-- pptx-preview 将在这里渲染 -->
          </div>
        </div>
        <!-- 不支持的 Office 类型 -->
        <div v-else class="flex flex-col items-center justify-center h-full text-muted-foreground">
          <FileText class="w-16 h-16 mb-3 opacity-50" />
          <p class="text-sm mb-1">{{ officeFileType }} 文件</p>
          <p class="text-xs text-muted-foreground/60 mb-4">此格式暂不支持预览</p>
          <Button variant="outline" size="sm" @click="openFile">
            <ExternalLink class="w-4 h-4 mr-1" />
            打开文件
          </Button>
        </div>
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
          <ExternalLink class="w-4 h-4 mr-1" />
          打开文件
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
  Image as ImageIcon
} from 'lucide-vue-next'
import { open } from '@tauri-apps/plugin-shell'
import { readTextFile, readFile } from '@tauri-apps/plugin-fs'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useThemeStore } from '@/stores/theme'
import * as XLSX from 'xlsx'
import mammoth from 'mammoth'
import JSZip from 'jszip'
import { init as initPptxPreview } from 'pptx-preview'

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
  }
})

// 状态
const loading = ref(false)
const error = ref(null)
const fileContent = ref('')
const copied = ref(false)
const htmlDataUrl = ref('')

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
  return props.fileName || props.filePath.split('/').pop() || 'file'
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
    'html': 'html', 'htm': 'html',
    'md': 'markdown', 'markdown': 'markdown',
    'excalidraw': 'excalidraw',
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
    'html': 'HTML',
    'markdown': 'Markdown',
    'excalidraw': 'Excalidraw',
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
    'html': '🌐',
    'markdown': '📝',
    'excalidraw': '✏️',
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

// Excalidraw 背景色 - 根据主题动态变化
const excalidrawBgColor = computed(() => {
  return isDark.value ? '#1e1e1e' : '#ffffff'
})

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

// 加载文件内容
const loadContent = async () => {
  if (fileType.value === 'other') return
  
  try {
    loading.value = true
    error.value = null
    
    if (['pdf', 'image'].includes(fileType.value)) {
      loading.value = false
      return
    }
    
    fileContent.value = await readTextFile(props.filePath)

    if (fileType.value === 'excalidraw') {
      try {
        const data = JSON.parse(fileContent.value)
        excalidrawElementCount.value = data.elements?.length || 0
        excalidrawBgColor.value = data.appState?.viewBackgroundColor || '#ffffff'

        const typeCount = {}
        data.elements?.forEach(el => {
          typeCount[el.type] = (typeCount[el.type] || 0) + 1
        })
        excalidrawTypeSummary.value = Object.entries(typeCount)
          .map(([type, count]) => `${type}: ${count}`)
          .join(', ')

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
    await open(props.filePath)
  } catch (err) {
    console.error('打开文件失败:', err)
  }
}

// 在 Excalidraw 打开
const openInExcalidraw = () => {
  window.open('https://excalidraw.com', '_blank')
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

  // PPT 文件使用 pptx-preview 单独处理
  if (ext === 'pptx' || ext === 'ppt') {
    await loadPptxPreview()
    return
  }

  officeLoading.value = true
  officeError.value = ''
  officeContent.value = null

  try {
    if (ext === 'docx' || ext === 'doc') {
      const html = await parseDocx(props.filePath)
      officeContent.value = DOMPurify.sanitize(html)
    } else if (ext === 'xlsx' || ext === 'xls') {
      const sheets = await parseXlsx(props.filePath)
      officeContent.value = sheets
    } else {
      officeError.value = '不支持的 Office 格式'
    }
  } catch (err) {
    console.error('加载 Office 文件失败:', err)
    officeError.value = err.message || '加载失败'
  } finally {
    officeLoading.value = false
  }
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
