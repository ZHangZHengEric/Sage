<template>
  <div class="file-preview my-3 border rounded-lg overflow-hidden bg-background">
    <!-- 头部：文件信息和操作 -->
    <div class="flex items-center justify-between px-3 py-2 bg-muted border-b">
      <div class="flex items-center gap-2 min-w-0">
        <span class="text-lg">{{ fileIcon }}</span>
        <span class="text-sm font-medium truncate">{{ fileName }}</span>
        <span class="text-xs text-muted-foreground">({{ fileType }})</span>
      </div>
      <div class="flex items-center gap-1 flex-shrink-0">
        <Button 
          variant="ghost" 
          size="sm"
          @click="toggleExpand"
          class="h-7 px-2"
        >
          <ChevronDown v-if="!isExpanded" class="w-4 h-4" />
          <ChevronUp v-else class="w-4 h-4" />
          <span class="ml-1 text-xs">{{ isExpanded ? '收起' : '展开' }}</span>
        </Button>
        <Button 
          variant="ghost" 
          size="sm"
          @click="openFile"
          class="h-7 px-2"
          title="打开文件"
        >
          <ExternalLink class="w-4 h-4" />
        </Button>
      </div>
    </div>
    
    <!-- 预览内容 -->
    <div v-show="isExpanded" class="preview-content">
      <!-- 加载中 -->
      <div v-if="loading" class="flex items-center justify-center py-8">
        <Loader2 class="w-6 h-6 animate-spin text-primary" />
        <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
      </div>
      
      <!-- 错误 -->
      <div v-else-if="error" class="p-4 text-destructive bg-destructive/10">
        <div class="flex items-center gap-2">
          <AlertCircle class="w-5 h-5" />
          <span class="text-sm">{{ error }}</span>
        </div>
        <Button 
          variant="outline" 
          size="sm"
          @click="loadContent"
          class="mt-2"
        >
          <RefreshCw class="w-4 h-4 mr-1" />
          重试
        </Button>
      </div>
      
      <!-- PDF 预览 -->
      <div v-else-if="fileType === 'pdf'" class="pdf-preview">
        <div v-if="!blobUrl" class="p-4 text-center text-muted-foreground bg-muted/30">
          <FileText class="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p class="text-sm mb-2">PDF 文件预览</p>
          <p class="text-xs text-muted-foreground/60 mb-3">加载中...</p>
        </div>
        <iframe 
            v-else 
            :src="blobUrl" 
            class="w-full h-[500px] border-0"
            title="PDF Viewer"
        ></iframe>
      </div>
      
      <!-- 图片预览 -->
      <div v-else-if="fileType === 'image'" class="image-preview p-2">
        <div v-if="!blobUrl" class="p-4 text-center text-muted-foreground bg-muted/30">
          <ImageIcon class="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p class="text-sm mb-2">图片文件</p>
          <p class="text-xs text-muted-foreground/60 mb-3">加载中...</p>
        </div>
        <div v-else class="flex justify-center">
            <img :src="blobUrl" class="max-w-full max-h-[400px] object-contain rounded" />
        </div>
      </div>
      
      <!-- HTML 预览 -->
      <div v-else-if="fileType === 'html'" class="html-preview">
        <div class="p-4 text-center text-muted-foreground bg-muted/30">
          <Globe class="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p class="text-sm mb-2">HTML 文件无法直接在预览中显示</p>
          <p class="text-xs text-muted-foreground/60 mb-3">由于浏览器安全限制，无法加载本地 HTML 文件</p>
          <Button 
            variant="outline" 
            size="sm"
            @click="openFile"
          >
            <ExternalLink class="w-4 h-4 mr-1" />
            在浏览器中打开
          </Button>
        </div>
      </div>
      
      <!-- Markdown 预览 -->
      <div v-else-if="fileType === 'markdown'" class="markdown-preview p-4 max-h-[400px] overflow-auto bg-background rounded">
        <div class="prose prose-sm max-w-none dark:prose-invert" v-html="renderedMarkdown"></div>
      </div>
      
      <!-- 代码文件预览 -->
      <div v-else-if="fileType === 'code'" class="code-preview">
        <div class="flex items-center justify-between px-3 py-1 bg-muted/50 border-b text-xs">
          <span class="text-muted-foreground">{{ language }}</span>
          <Button 
            variant="ghost" 
            size="sm"
            @click="copyContent"
            class="h-6 px-2"
          >
            <Copy v-if="!copied" class="w-3 h-3 mr-1" />
            <Check v-else class="w-3 h-3 mr-1" />
            {{ copied ? '已复制' : '复制' }}
          </Button>
        </div>
        <pre class="p-3 text-xs overflow-auto max-h-[350px] bg-muted/30"><code>{{ fileContent }}</code></pre>
      </div>
      
      <!-- Excalidraw 预览 - SVG 渲染 -->
      <div v-else-if="fileType === 'excalidraw'" class="excalidraw-preview">
        <div class="p-3" :style="{ backgroundColor: excalidrawBgColor }">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2 text-xs text-muted-foreground">
              <span>{{ excalidrawElementCount }} 个元素</span>
              <span v-if="excalidrawTypeSummary" class="text-muted-foreground/50">|</span>
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
          <div class="overflow-auto max-h-[400px] border border-border/30 rounded bg-white/80">
            <svg 
              :viewBox="`0 0 ${excalidrawWidth + 100} ${excalidrawHeight + 100}`" 
              class="w-full h-auto"
              style="min-height: 200px;"
              v-html="excalidrawSvg"
            ></svg>
          </div>
          <div v-if="excalidrawElementCount > 100" class="mt-2 text-[10px] text-muted-foreground/60 text-center">
            仅显示前 100 个元素
          </div>
        </div>
      </div>
      
      <!-- 文本文件预览 -->
      <div v-else-if="fileType === 'text'" class="text-preview">
        <pre class="p-3 text-xs overflow-auto max-h-[350px] bg-muted/30"><code>{{ fileContent }}</code></pre>
      </div>

      <!-- Office 文件预览 -->
      <div v-else-if="fileType === 'office'" class="office-preview">
        <div class="p-4 text-center text-muted-foreground bg-muted/30">
          <FileText class="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p class="text-sm mb-2">{{ officeFileType }} 文件</p>
          <p class="text-xs text-muted-foreground/60 mb-3">Office 文件无法直接在浏览器中预览</p>
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

      <!-- 其他文件 -->
      <div v-else class="other-preview p-4 text-center text-muted-foreground">
        <File class="w-12 h-12 mx-auto mb-2 opacity-50" />
        <p class="text-sm">此文件类型暂不支持预览</p>
        <Button 
          variant="outline" 
          size="sm"
          @click="openFile"
          class="mt-2"
        >
          <ExternalLink class="w-4 h-4 mr-1" />
          打开文件
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Button } from '@/components/ui/button'
import { 
  ChevronDown, 
  ChevronUp, 
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
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { agentAPI } from '@/api/agent'

const props = defineProps({
  filePath: {
    type: String,
    required: true
  },
  agentId: {
    type: String,
    default: ''
  },
  autoLoad: {
    type: Boolean,
    default: true
  },
  defaultExpanded: {
    type: Boolean,
    default: true
  }
})

// 状态
const loading = ref(false)
const error = ref(null)
const fileContent = ref('')
const blobUrl = ref('')
const isExpanded = ref(props.defaultExpanded)
const copied = ref(false)

// 文件信息
const fileName = computed(() => {
  return props.filePath.split('/').pop() || 'file'
})

const fileExtension = computed(() => {
  const name = fileName.value
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

// 文件图标
const fileIcon = computed(() => {
  const icons = {
    'pdf': '📄',
    'image': '🖼️',
    'html': '🌐',
    'markdown': '📝',
    'excalidraw': '🔷',
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

// Excalidraw 特定数据
const excalidrawBgColor = ref('#ffffff')
const excalidrawElementCount = ref(0)
const excalidrawTypeSummary = ref('')
const excalidrawWidth = ref(800)
const excalidrawHeight = ref(600)
const excalidrawSvg = ref('')

// Markdown 渲染
const renderedMarkdown = computed(() => {
  if (fileType.value !== 'markdown' || !fileContent.value) return ''
  const html = marked(fileContent.value)
  return DOMPurify.sanitize(html)
})

// 切换展开/收起
const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
  if (isExpanded.value && !fileContent.value && !blobUrl.value && !loading.value && props.autoLoad) {
    loadContent()
  }
}

// 生成 Excalidraw SVG
const generateExcalidrawSvg = (data) => {
  if (!data.elements || !Array.isArray(data.elements)) return ''
  
  // 计算画布边界
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
  
  // 生成 SVG 元素（只渲染前100个）
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
    
    if (!props.agentId) {
        throw new Error('未找到Agent ID，无法下载文件')
    }

    // 下载文件 Blob
    const blob = await agentAPI.downloadFile(props.agentId, props.filePath)
    
    // 如果是图片或PDF，创建 Blob URL
    if (['pdf', 'image', 'html'].includes(fileType.value)) {
        if (blobUrl.value) URL.revokeObjectURL(blobUrl.value)
        blobUrl.value = URL.createObjectURL(blob)
        loading.value = false
        return
    }
    
    // 如果是文本类文件，读取内容
    if (['markdown', 'code', 'text', 'excalidraw'].includes(fileType.value)) {
        fileContent.value = await blob.text()
    }
    
    // 解析 Excalidraw 数据
    if (fileType.value === 'excalidraw') {
      try {
        const data = JSON.parse(fileContent.value)
        excalidrawElementCount.value = data.elements?.length || 0
        excalidrawBgColor.value = data.appState?.viewBackgroundColor || '#ffffff'
        
        // 统计元素类型
        const typeCount = {}
        data.elements?.forEach(el => {
          typeCount[el.type] = (typeCount[el.type] || 0) + 1
        })
        excalidrawTypeSummary.value = Object.entries(typeCount)
          .map(([type, count]) => `${type}: ${count}`)
          .join(', ')
        
        // 生成 SVG
        excalidrawSvg.value = generateExcalidrawSvg(data)
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
  try {
    if (!props.agentId) return
    
    let url = blobUrl.value
    if (!url) {
        const blob = await agentAPI.downloadFile(props.agentId, props.filePath)
        url = URL.createObjectURL(blob)
        // 临时 URL，稍后清理
        setTimeout(() => URL.revokeObjectURL(url), 60000)
    }
    
    const a = document.createElement('a')
    a.href = url
    a.download = fileName.value
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
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

// 自动加载
onMounted(() => {
  if (props.autoLoad && isExpanded.value) {
    loadContent()
  }
})
</script>

<style scoped>
.file-preview {
  max-width: 100%;
}

.preview-content {
  min-height: 50px;
}

.pdf-preview iframe,
.html-preview iframe {
  display: block;
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
</style>
