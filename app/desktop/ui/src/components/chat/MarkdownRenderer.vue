<template>
  <div
    class="prose prose-xs dark:prose-invert max-w-none break-words"
    :class="props.compact ? 'text-[11px] leading-5' : 'text-sm'"
    v-html="renderedContent"
    @click="handleMarkdownClick"
  ></div>
</template>

<script setup>
import {computed, nextTick, onMounted, onUnmounted, ref, watch} from 'vue'
import {marked} from 'marked'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'
import mermaid from 'mermaid'
import { open } from '@tauri-apps/plugin-shell'
import { readFile } from '@tauri-apps/plugin-fs'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypePrism from 'rehype-prism-plus'
import rehypeStringify from 'rehype-stringify'
import { visit } from 'unist-util-visit'
import { toast } from 'vue-sonner'
import { setDebugCounter } from '@/utils/memoryDebug'
import { isAbsoluteLocalPath, isRelativeWorkspacePath, normalizeFileReference, resolveAgentWorkspacePath } from '@/utils/agentWorkspacePath'

// 不使用 prism 默认主题，使用自定义样式

// 初始化 Mermaid
mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'strict',
}) 

const props = defineProps({
  content: {
    type: String,
    default: ''
  },
  remarkPlugins: {
    type: Array,
    default: () => []
  },
  components: {
    type: Object,
    default: () => ({})
  },
  compact: {
    type: Boolean,
    default: false
  },
  agentId: {
    type: String,
    default: ''
  }
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

const jsToJson = (jsStr) => {
  // 移除注释
  jsStr = jsStr.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')

  // 添加属性名的引号（处理: key: value 格式）
  jsStr = jsStr.replace(/([{,]\s*)([a-zA-Z_$][a-zA-Z0-9_$]*)\s*:/g, '$1"$2":')

  // 处理未加引号的字符串值（简单处理：以'开头的字符串）
  jsStr = jsStr.replace(/:\s*'([^']*)'/g, ': "$1"')

  return jsStr
}

const chartList = [] // 存放所有图表容器与配置项
const mermaidList = [] // 存放所有 mermaid 图表
const excalidrawList = [] // 存放所有 excalidraw 图表
const chartInstances = ref([])
const localImageObjectUrls = ref([])
const renderer = new marked.Renderer()

// 修改 renderer.code，不再使用 Prism，只返回基础 HTML
renderer.code = (code, language) => {
  // 获取代码文本，兼容不同版本的 marked
  const codeText = typeof code === 'string' ? code : code.text
  // 优先从 token 对象中获取 lang，其次是 language 参数，最后默认为 plaintext
  const rawLang = (typeof code === 'string' ? language : code.lang) || ''
  const lang = rawLang.split(/\s+/)[0] || 'text'

  if (lang === 'echarts') {
    try {
      // 移除 option = 前缀和末尾的分号
      let chartCode = codeText.replace(/^[\s\S]*?=\s*/, '').trim()
      if (chartCode.endsWith(';')) {
        chartCode = chartCode.slice(0, -1).trim()
      }
      const id = `chart-${Math.random().toString(36).substr(2, 9)}`
      const jsonStr = jsToJson(chartCode)
      const option = JSON.parse(jsonStr)
      chartList.push({id, option})
      return `<div id="${id}" class="w-full h-[300px] my-4"></div>`
    } catch (err) {
      console.error('ECharts 配置解析失败:', err)
      return `<pre class="text-destructive p-4 border border-destructive/50 rounded bg-destructive/10">图表配置错误: ${err.message}</pre>`
    }
  }

  if (lang === 'mermaid') {
    const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`
    mermaidList.push({id, code: codeText})
    return `<div id="${id}" class="mermaid my-4 flex justify-center">${escapeHtml(codeText)}</div>`
  }

  if (lang === 'excalidraw') {
    // 尝试解析并显示 Excalidraw 预览
    try {
      const data = JSON.parse(codeText)
      const elementCount = data.elements?.length || 0
      const appState = data.appState || {}
      const bgColor = appState.viewBackgroundColor || '#ffffff'
      
      return `
        <div class="excalidraw-preview my-4 border rounded-lg overflow-hidden bg-white">
          <div class="flex items-center justify-between px-3 py-2 bg-muted border-b">
            <div class="flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-primary">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
              <span class="text-sm font-medium">Excalidraw 图表</span>
              <span class="text-xs text-muted-foreground">(${elementCount} 个元素)</span>
            </div>
            <div class="flex items-center gap-1">
              <button 
                onclick="this.closest('.excalidraw-preview').querySelector('.excalidraw-content').classList.toggle('hidden')"
                class="px-2 py-1 text-xs bg-background hover:bg-muted rounded border"
              >
                显示/隐藏 JSON
              </button>
            </div>
          </div>
          <div class="excalidraw-content hidden p-3 bg-muted/30">
            <pre class="text-xs overflow-auto max-h-[200px]"><code>${escapeHtml(codeText.substring(0, 2000))}${codeText.length > 2000 ? '...' : ''}</code></pre>
          </div>
          <div class="p-3 text-sm text-muted-foreground bg-[${bgColor}]" style="background-color: ${bgColor}">
            <p>💡 提示：将内容保存为 .excalidraw 文件，然后在 <a href="https://excalidraw.com" target="_blank" class="text-primary underline">Excalidraw</a> 中打开查看完整图表</p>
          </div>
        </div>
      `
    } catch (e) {
      return `<pre class="text-destructive p-4 border border-destructive/50 rounded bg-destructive/10">无效的 Excalidraw 格式: ${e.message}</pre>`
    }
  }

  return `<pre><code class="language-${lang}">${escapeHtml(codeText)}</code></pre>`
}

renderer.table = function(token) {
  let header = ''
  let body = ''
  
  // 生成表头
  let headerContent = ''
  for (const cell of token.header) {
    headerContent += this.tablecell(cell)
  }
  header = `<tr>${headerContent}</tr>`

  // 生成表体
  for (const row of token.rows) {
    let rowContent = ''
    for (const cell of row) {
      rowContent += this.tablecell(cell)
    }
    body += `<tr>${rowContent}</tr>`
  }

  return `<div class="overflow-x-auto my-4 w-full">
    <table class="w-full text-xs border-collapse border rounded-md">
      <thead class="bg-muted/50">
        ${header}
      </thead>
      <tbody>
        ${body}
      </tbody>
    </table>
  </div>`
}

renderer.tablecell = function(token) {
  const content = this.parser.parseInline(token.tokens)
  const tag = token.header ? 'th' : 'td'
  let className = token.header
    ? 'border px-3 py-1.5 text-left font-medium text-muted-foreground'
    : 'border px-3 py-1.5'

  if (token.align) {
    className += ` text-${token.align}`
  }

  return `<${tag} class="${className}">${content}</${tag}>`
}

// 配置marked选项
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false,
  renderer
})

// Rehype 插件：代码块处理（简化样式，直接显示）
const rehypeCodeBlockWrapper = () => {
  return (tree) => {
    visit(tree, 'element', (node, index, parent) => {
      // 找到 pre 元素，并且它包含一个 code 元素
      if (node.tagName === 'pre' && node.children && node.children.length > 0) {
        const codeNode = node.children.find(n => n.tagName === 'code')
        if (codeNode) {
          // 获取语言
          let lang = 'text'

          // 检查 code 元素上的 class
          if (codeNode.properties && codeNode.properties.className) {
            const classes = Array.isArray(codeNode.properties.className)
              ? codeNode.properties.className
              : [codeNode.properties.className]

            const langClass = classes.find(c => String(c).startsWith('language-'))
            if (langClass) {
              lang = String(langClass).replace('language-', '')
            }
          }

          // 如果 code 上没找到，检查 pre 上的 class
          if (lang === 'text' && node.properties && node.properties.className) {
             const classes = Array.isArray(node.properties.className)
              ? node.properties.className
              : [node.properties.className]

            const langClass = classes.find(c => String(c).startsWith('language-'))
            if (langClass) {
              lang = String(langClass).replace('language-', '')
            }
          }

          // 直接修改 pre 元素的样式，不添加卡片包裹
          node.properties = {
            ...node.properties,
            className: [
              'my-3',
              'p-3',
              'rounded-lg',
              'overflow-auto',
              'text-xs',
              'font-mono',
              'leading-relaxed',
              'bg-slate-100',
              'dark:bg-slate-800',
              'text-slate-800',
              'dark:text-slate-200',
              'border',
              'border-slate-200',
              'dark:border-slate-700'
            ]
          }

          // 添加 data-language 属性用于显示语言
          node.properties['data-language'] = lang
        }
      }
    })
  }
}

// 检测视频链接的正则表达式
const videoExtensions = /\.(mp4|webm|ogg|mov|avi|mkv)$/i
// 检测图片链接的正则表达式
const imageExtensions = /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i

// 下载图片函数
const downloadImage = (url, filename) => {
  fetch(url)
      .then(response => response.blob())
      .then(blob => {
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob)
        link.download = filename || 'image'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(link.href)
      })
      .catch(error => {
        console.error('下载图片失败:', error)
        const link = document.createElement('a')
        link.href = url
        link.download = filename || 'image'
        link.target = '_blank'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
      })
}

// 将图片添加下载按钮
const addImageDownloadButton = (html) => {
  return html.replace(/<img([^>]*)>/g, (match, attrs) => {
    // 提取 src 属性
    const srcMatch = attrs.match(/src="([^"]*)"/)
    const src = srcMatch ? srcMatch[1] : ''
    // 提取 data-local-image 属性（本地图片标记）
    const localImageMatch = attrs.match(/data-local-image="([^"]*)"/)
    const localImagePath = localImageMatch ? localImageMatch[1] : ''
    
    const filename = (src || localImagePath).split('/').pop().split('?')[0] || 'image'
    
    // 检查是否为本地路径（file://、asset://、绝对路径，或有 data-local-image 属性）
    const isLocal = src.startsWith('file://') || src.startsWith('asset://') || src.startsWith('/') || !!localImagePath
    
    // 本地图片：显示复制到下载目录按钮
    if (isLocal) {
      const pathToCopy = localImagePath || src
      return `<div class="relative group inline-block max-w-full my-2">
        <img${attrs} class="rounded-lg max-w-full h-auto block border">
        <button class="absolute top-2 right-2 p-1.5 bg-background/80 backdrop-blur-sm rounded-md shadow-sm opacity-0 group-hover:opacity-100 transition-opacity hover:bg-background text-foreground border" onclick="window.copyLocalImageToDownloads('${pathToCopy}', '${filename}')" title="复制到下载目录">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-4 h-4">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7,10 12,15 17,10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
        </button>
      </div>`
    }
    
    // 在线图片：显示下载按钮
    return `<div class="relative group inline-block max-w-full my-2">
      <img${attrs} class="rounded-lg max-w-full h-auto block border">
      <button class="absolute top-2 right-2 p-1.5 bg-background/80 backdrop-blur-sm rounded-md shadow-sm opacity-0 group-hover:opacity-100 transition-opacity hover:bg-background text-foreground border" onclick="window.downloadMarkdownImage('${src}', '${filename}')" title="下载图片">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-4 h-4">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="7,10 12,15 17,10"></polyline>
          <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
      </button>
    </div>`
  })
}

// 文件类型图标映射
const getFileIcon = (filename) => {
  const ext = filename.split('.').pop().toLowerCase()
  const iconMap = {
    // 图片
    'png': '🖼️', 'jpg': '🖼️', 'jpeg': '🖼️', 'gif': '🖼️',
    'webp': '🖼️', 'svg': '🎨', 'bmp': '🖼️', 'ico': '🎨',
    // 文档
    'pdf': '📄',
    'doc': '📝', 'docx': '📝',
    'xls': '📊', 'xlsx': '📊',
    'ppt': '📽️', 'pptx': '📽️',
    'txt': '📃',
    'md': '📑',
    // 视频
    'mp4': '🎬', 'webm': '🎬', 'mov': '🎬', 'avi': '🎬',
    // 音频
    'mp3': '🎵', 'wav': '🎵', 'ogg': '🎵',
    // 代码
    'js': '📜', 'ts': '📜', 'py': '📜', 'java': '📜', 'cpp': '📜', 'c': '📜', 'go': '📜', 'rs': '📜',
    'html': '🌐', 'css': '🎨', 'vue': '💚', 'jsx': '⚛️', 'tsx': '⚛️',
    'json': '📋', 'xml': '📋', 'yaml': '📋', 'yml': '📋',
    // 压缩包
    'zip': '📦', 'rar': '📦', '7z': '📦', 'tar': '📦', 'gz': '📦',
    // 其他
    'csv': '📊', 'sql': '🗄️', 'exe': '⚙️', 'dmg': '💿', 'apk': '📱'
  }
  return iconMap[ext] || '📎' // 默认图标
}

// 检测是否为文件链接（有扩展名且不是图片）
const isFileLink = (url) => {
  try {
    const cleanUrl = url.split(/[?#]/)[0]
    const filename = cleanUrl.split('/').pop()
    if (!filename || !filename.includes('.') || filename.endsWith('.')) {
      return false
    }
    // 排除图片文件
    const ext = filename.split('.').pop().toLowerCase()
    const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico']
    return !imageExts.includes(ext)
  } catch (e) {
    return false
  }
}

const convertHttpLinksToDownload = (html) => {
  return html.replace(
    /<a([^>]*?)href="(https?:\/\/[^"]+)"([^>]*)>(.*?)<\/a>/gi,
    (match, pre, href, post, text) => {
      if (/\sdownload(\s|$|=)/i.test(pre) || /\sdownload(\s|$|=)/i.test(post)) return match
      if (/<img/i.test(text)) return match
      let filename = 'download'
      try {
        let cleanUrl = href.split(/[?#]/)[0]
        cleanUrl = decodeURIComponent(cleanUrl)
        if (cleanUrl.endsWith('/')) cleanUrl = cleanUrl.slice(0, -1)
        filename = cleanUrl.split('/').pop() || 'download'
      } catch (e) { console.warn('解析URL文件名失败:', e) }

      // 如果是文件链接，添加图标
      const icon = isFileLink(href) ? getFileIcon(filename) : '🔗'

      return `
        <a
          href="${href.replace(/ /g, '%20')}"
          download="${filename}"
          target="_blank"
          rel="noopener"
          class="text-primary underline underline-offset-4 hover:opacity-80 inline-flex items-center gap-1"
        >
          <span class="file-icon">${icon}</span>
          <span>${filename}</span>
        </a>
      `
    }
  )
}

const convertVideoLinks = (html) => {
  html = html.replace(/<a[^>]*href="([^"]*)"[^>]*>([^<]*)<\/a>/g, (match, url, text) => {
    if (videoExtensions.test(url)) {
      return `<video controls class="w-full rounded-lg my-4 border bg-black/5">
        <source src="${url}" type="video/mp4">
        您的浏览器不支持视频播放。
      </video>`
    }
    return match
  })
  html = html.replace(/(?<!src="|href=")https?:\/\/[^\s<>"]+\.(mp4|webm|ogg|mov|avi|mkv)(?:\?[^\s<>"]*)?/gi, (match) => {
    return `<video controls class="w-full rounded-lg my-4 border bg-black/5">
      <source src="${match}" type="video/mp4">
      您的浏览器不支持视频播放。
    </video>`
  })
  return html
}

const unixAbsolutePathPattern = /^\/((Users|home|Volumes|private|tmp|var|opt|Applications|System|Library)\/.+|\.sage\/.+)/
const windowsAbsolutePathPattern = /^[a-zA-Z]:[\\/]/
const fileProtocolPattern = /^file:\/\//i

const normalizeLocalPath = (path) => {
  return normalizeFileReference(path)
}

const isLocalAbsolutePath = (path) => {
  if (!path) return false
  // 如果已经是 file:// 协议，直接认为是本地路径
  if (fileProtocolPattern.test(path)) {
    return true
  }
  const normalized = normalizeLocalPath(path)
  return isAbsoluteLocalPath(normalized) || unixAbsolutePathPattern.test(normalized) || windowsAbsolutePathPattern.test(normalized)
}

const toFileUrl = (localPath) => {
  // 如果已经是 asset:// 或 http:// URL，直接返回
  if (localPath.startsWith('asset://') || localPath.startsWith('http://') || localPath.startsWith('https://')) {
    return localPath
  }
  // 使用 Tauri 的 convertFileSrc 转换本地路径
  let cleanPath = localPath
  // 如果已经是 file:// 协议，去掉协议头
  if (/^file:\/\//i.test(localPath)) {
    cleanPath = localPath.replace(/^file:\/\//i, '')
  }
  // 去掉开头的 /，因为 convertFileSrc 会将其编码为 %2F
  cleanPath = cleanPath.replace(/^\//, '')
  return convertFileSrc(cleanPath)
}

const convertLocalPathLinksToSystemOpen = (html) => {
  return html.replace(
    /<a([^>]*?)href="([^"]+)"([^>]*)>(.*?)<\/a>/gi,
    (match, pre, href, post, text) => {
      // 如果链接已经有 file-icon，说明已经在 preprocessContent 中处理过了
      if (text.includes('file-icon')) return match
      if (!isLocalAbsolutePath(href)) return match
      const localPath = normalizeLocalPath(href)
      const filename = localPath.split('/').pop() || 'file'

      // 获取文件图标
      const icon = getFileIcon(filename)

      return `
        <a
          ${pre}
          href="${escapeHtml(href)}"
          ${post}
          data-local-path="${escapeHtml(localPath)}"
          onclick="window.openMarkdownLocalPath(this); return false;"
          class="text-primary underline underline-offset-4 hover:opacity-80 inline-flex items-center gap-1 break-all cursor-pointer select-none"
        >
          <span class="file-icon">${icon}</span>
          <span>${text || filename}</span>
        </a>
      `
    }
  )
}

const preprocessContent = (content) => {
  if (!content) return ''
  
  // 处理 skill 标签，转换为特殊格式
  let processed = content.replace(
    /<skill>(.*?)<\/skill>/gi,
    (match, skillName) => {
      const trimmedName = skillName.trim()
      return `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-primary/10 text-primary text-xs font-medium border border-primary/20 mx-0.5 align-middle">
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-3 h-3"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
        ${trimmedName}
      </span>`
    }
  )
  
  // 处理 Markdown 图片 - 将本地图片路径标记为 data-local-image，稍后异步加载
  // 匹配 ![alt](/path/to/image.png) 或 ![alt](file:///path/to/image.png) 格式
  processed = processed.replace(
    /!\[([^\]]*)\]\((file:\/\/[^)]+|\/(?:[^()]*|\([^)]*\))*)\)/g,
    (match, alt, path) => {
      // 检查是否是本地绝对路径且是图片
      if ((isLocalAbsolutePath(path) || (props.agentId && isRelativeWorkspacePath(path))) && imageExtensions.test(path)) {
        // 标记为本地图片，稍后异步加载，限制最大高度为 400px
        return `<img data-local-image="${escapeHtml(normalizeLocalPath(path))}" alt="${escapeHtml(alt)}" class="rounded-lg max-w-full max-h-[300px] h-auto block border my-2 object-contain" src="">`
      }
      return match
    }
  )

  // 处理本地文件链接 - 将 Markdown 格式的本地文件链接转换为 HTML，避免 marked 解析问题
  // 匹配 [text](/path/to/file) 或 [text](file:///path/to/file) 格式，路径可以包含括号
  console.log('[MarkdownRenderer] Before file link processing:', processed.substring(0, 500))
  // 匹配 Markdown 链接 [text](url)，支持 file:// 协议和本地路径
  // 使用非贪婪匹配，避免跨链接匹配
  processed = processed.replace(
    /\[([^\]]*)\]\((file:\/\/[^\s)]+|\/[^\s)]*|[A-Za-z0-9_.-]+[\\/][^\s)]*)\)/g,
    (match, text, path) => {
      const isWorkspaceRelative = !!props.agentId && isRelativeWorkspacePath(path)
      console.log('[MarkdownRenderer] Found file link:', { text, path, isLocal: isLocalAbsolutePath(path), isWorkspaceRelative, isImage: imageExtensions.test(path) })
      // 检查是否是本地绝对路径
      if (isLocalAbsolutePath(path) || isWorkspaceRelative) {
        // 检查是否为图片文件
        if (imageExtensions.test(path)) {
          // 图片文件标记为 data-local-image，稍后异步加载，限制最大高度为 400px
          const alt = text.trim() || path.split('/').pop() || 'image'
          console.log('[MarkdownRenderer] Marking as local image:', path)
          return `<img data-local-image="${escapeHtml(normalizeLocalPath(path))}" alt="${escapeHtml(alt)}" class="rounded-lg max-w-full max-h-[200px] h-auto block border my-2 object-contain" src="">`
        }
        // 非图片文件显示为文件链接
        const icon = getFileIcon(path.split('/').pop() || 'file')
        // 如果 [] 中的文字为空，使用路径中的文件名
        let displayText = text.trim()
        if (!displayText) {
          displayText = path.split('/').pop() || 'file'
          // 清理文件名，去掉时间戳后缀
          displayText = displayText.replace(/_\d{14}\.([^.]+)$/, '.$1')
        }
        return `<a href="${escapeHtml(path)}" data-local-path="${escapeHtml(normalizeLocalPath(path))}" onclick="window.openMarkdownLocalPath(this); return false;" class="text-primary underline underline-offset-4 hover:opacity-80 inline-flex items-center gap-1 break-all cursor-pointer select-none"><span class="file-icon">${icon}</span><span>${escapeHtml(displayText)}</span></a>`
      }
      return match
    }
  )
  console.log('[MarkdownRenderer] After file link processing:', processed.substring(0, 500))

  // 处理 HTTP 文件链接
  processed = processed.replace(
    /(https?:\/\/[^\n\r"<>]+?\.(?:pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|tar|gz|bz2|txt|csv|json|xml|md|jpg|jpeg|png|gif|svg|webp|mp4|webm|mp3|wav))/gi,
    (match) => match.replace(/\s/g, '%20')
  )

  // 处理纯文本的本地图片路径（不在链接中的图片路径）
  // 匹配 file:///path/to/image.png 或 /path/to/image.png
  processed = processed.replace(
    /(^|\s)(file:\/\/[^\n\r"<>]+|\/[^\n\r"<>]+)\.(jpg|jpeg|png|gif|svg|webp|bmp|ico)($|\s)/gi,
    (match, prefix, path, ext, suffix) => {
      const fullPath = path + '.' + ext
      if (isLocalAbsolutePath(fullPath)) {
        const fileUrl = toFileUrl(normalizeLocalPath(fullPath))
        const alt = fullPath.split('/').pop() || 'image'
        return `${prefix}<img src="${fileUrl}" alt="${escapeHtml(alt)}" class="rounded-lg max-w-full h-auto block border my-2">${suffix}`
      }
      return match
    }
  )

  return processed
}

const renderedContent = computed(() => {
  if (!props.content) return ''

  try {
    console.log('[MarkdownRenderer] Original content:', props.content.substring(0, 1000))
    chartList.length = 0
    mermaidList.length = 0
    excalidrawList.length = 0
    const preprocessed = preprocessContent(props.content)
    console.log('[MarkdownRenderer] Preprocessed content:', preprocessed.substring(0, 1000))
    let html = marked(preprocessed)
    console.log('[MarkdownRenderer] Marked HTML:', html.substring(0, 1000))

    // Unified Pipeline: Parse -> Highlight -> Stringify
    const processed = unified()
      .use(rehypeParse, { fragment: true })
      .use(rehypePrism, { ignoreMissing: true })
      .use(rehypeCodeBlockWrapper)
      .use(rehypeStringify)
      .processSync(html)
    
    html = String(processed)

    // Post-processing
    html = convertVideoLinks(html)
    html = convertHttpLinksToDownload(html)
    html = convertLocalPathLinksToSystemOpen(html)
    html = addImageDownloadButton(html)

    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'u', 'del', 'code', 'pre',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'blockquote',
        'a', 'img',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'div', 'span', 'button', 'svg', 'path', 'polyline', 'line', 'rect',
        'video', 'source'
      ],
      ALLOWED_ATTR: [
        'href', 'src', 'alt', 'title', 'class', 'id',
        'target', 'rel', 'controls', 'type', 'onclick',
        'data-local-path',
        'width', 'height', 'viewBox', 'fill', 'stroke', 'stroke-width',
        'stroke-linecap', 'stroke-linejoin',
        'points', 'x1', 'y1', 'x2', 'y2', 'd', 'x', 'y', 'rx', 'ry',
        'style' // Prism uses style for some highlights
      ]
    })
  } catch (error) {
    console.error('Markdown渲染错误:', error)
    return props.content
  }
})

// 渲染 ECharts
const disposeCharts = () => {
  chartInstances.value.forEach((instance) => {
    try {
      instance.dispose()
    } catch (err) {
      console.warn('释放 ECharts 实例失败:', err)
    }
  })
  chartInstances.value = []
  setDebugCounter('chatMarkdown.chartInstances', 0)
}

const revokeLocalImageObjectUrls = () => {
  localImageObjectUrls.value.forEach((url) => {
    try {
      URL.revokeObjectURL(url)
    } catch (err) {
      console.warn('释放本地图片 URL 失败:', err)
    }
  })
  localImageObjectUrls.value = []
  setDebugCounter('chatMarkdown.localImageObjectUrls', 0)
}

const renderCharts = async () => {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 200))

  disposeCharts()

  chartList.forEach(({id, option}) => {
    const el = document.getElementById(id)
    if (el && el.clientWidth > 0 && el.clientHeight > 0) {
      try {
        const existing = echarts.getInstanceByDom(el)
        if (existing) {
          existing.dispose()
        }
        const chart = echarts.init(el)
        chart.setOption(option)
        chartInstances.value.push(chart)
        setDebugCounter('chatMarkdown.chartInstances', chartInstances.value.length)
      } catch (err) {
        console.error(`✗ 图表 ${id} 初始化失败:`, err)
      }
    }
  })
}

// 渲染 Mermaid
const renderMermaid = async () => {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 100))

  for (const {id, code} of mermaidList) {
    const el = document.getElementById(id)
    if (!el) continue

    try {
      // 使用 mermaid.render 生成 SVG
      const { svg } = await mermaid.render(`mermaid-svg-${id}`, code)
      el.innerHTML = svg
      el.classList.add('mermaid-rendered')
    } catch (err) {
      console.error(`✗ Mermaid 图表 ${id} 渲染失败:`, err)
      el.innerHTML = `<pre class="text-destructive p-4 border border-destructive/50 rounded bg-destructive/10">Mermaid 渲染错误: ${err.message}</pre>`
    }
  }
}

// 异步加载本地图片
const loadLocalImages = async () => {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 100))

  revokeLocalImageObjectUrls()

  // 查找所有带有 data-local-image 属性的 img 标签
  const images = document.querySelectorAll('img[data-local-image]')
  console.log('[MarkdownRenderer] Found local images:', images.length)

  for (const img of images) {
    const localPath = img.getAttribute('data-local-image')
    if (!localPath) continue
    const resolvedLocalPath = await resolveAgentWorkspacePath(localPath, props.agentId)

    try {
      console.log('[MarkdownRenderer] Loading image:', resolvedLocalPath)

      // 检查是否为 SVG 文件
      if (resolvedLocalPath.toLowerCase().endsWith('.svg')) {
        // SVG 文件：读取文本内容并内联渲染
        const { readTextFile } = await import('@tauri-apps/plugin-fs')
        const svgContent = await readTextFile(resolvedLocalPath)
        // 清理 SVG 内容
        const cleanedSvg = svgContent
          .replace(/<\?xml[^?]*\?>/gi, '')
          .replace(/<!DOCTYPE[^>]*>/gi, '')
          .trim()
        // 创建 SVG 容器
        const wrapper = document.createElement('div')
        wrapper.className = 'svg-inline-wrapper my-2'
        wrapper.style.maxWidth = '100%'
        wrapper.style.overflow = 'auto'
        wrapper.innerHTML = cleanedSvg
        // 替换 img 标签（检查 parentNode 是否存在）
        if (img.parentNode) {
          img.parentNode.replaceChild(wrapper, img)
        }
        continue
      }

      // 其他图片：读取文件内容为 Uint8Array
      const fileData = await readFile(resolvedLocalPath)
      console.log('[MarkdownRenderer] File loaded, size:', fileData.length)

      // 转换为 Blob
      const blob = new Blob([fileData])

      // 创建 Object URL
      const objectUrl = URL.createObjectURL(blob)
      console.log('[MarkdownRenderer] Created object URL:', objectUrl)
      localImageObjectUrls.value.push(objectUrl)
      setDebugCounter('chatMarkdown.localImageObjectUrls', localImageObjectUrls.value.length)

      // 设置 img 的 src
      img.src = objectUrl
      img.removeAttribute('data-local-image')
    } catch (error) {
      console.error('[MarkdownRenderer] Failed to load image:', resolvedLocalPath, error)
      // 显示错误占位符（检查 img 是否还在 DOM 中）
      if (img && img.parentNode) {
        img.alt = `加载失败: ${resolvedLocalPath.split('/').pop()}`
      }
    }
  }
}

const resolveAnchorFromEvent = (event) => {
  const rawTarget = event?.target
  if (!rawTarget) return null
  if (typeof rawTarget.closest === 'function') {
    return rawTarget.closest('a')
  }
  if (rawTarget.parentElement && typeof rawTarget.parentElement.closest === 'function') {
    return rawTarget.parentElement.closest('a')
  }
  return null
}

const getErrorDetail = (error) => {
  if (!error) return 'unknown'
  if (typeof error === 'string') return error
  if (error.message) return error.message
  if (error.reason) return String(error.reason)
  try {
    const serialized = JSON.stringify(error)
    if (serialized && serialized !== '{}') return serialized
  } catch (e) {
  }
  return String(error)
}

const handleMarkdownClick = async (event) => {
  const target = resolveAnchorFromEvent(event)
  if (!target) return
  const localPath = target.getAttribute('data-local-path') || target.getAttribute('href') || ''
  if (!isLocalAbsolutePath(localPath) && !(props.agentId && isRelativeWorkspacePath(localPath))) return
  event.preventDefault()
  if (typeof window !== 'undefined' && typeof window.openMarkdownLocalPath === 'function') {
    await window.openMarkdownLocalPath(target)
  }
}

// Global functions setup
onMounted(() => {
  if (typeof window !== 'undefined') {
    window.downloadMarkdownImage = downloadImage
    window.openMarkdownLocalPath = async (element) => {
      const raw = element?.getAttribute('data-local-path') || element?.getAttribute('href') || ''
      const localPath = await resolveAgentWorkspacePath(raw, props.agentId)
      if (!isLocalAbsolutePath(localPath)) {
        if (raw) window.open(raw, '_blank')
        return
      }
      try {
        await open(localPath)
      } catch (error1) {
        const fallbackUrl = toFileUrl(localPath)
        try {
          await open(fallbackUrl)
        } catch (error2) {
          const detail1 = getErrorDetail(error1)
          const detail2 = getErrorDetail(error2)
          console.error('打开本地文件失败:', localPath, detail1, detail2)
        }
      }
    }
    
    // 复制本地图片到下载目录
    window.copyLocalImageToDownloads = async (localPath, filename) => {
      try {
        const { readFile } = await import('@tauri-apps/plugin-fs')
        const { save } = await import('@tauri-apps/plugin-dialog')
        
        // 读取文件内容
        const fileData = await readFile(localPath)
        
        // 弹出保存对话框
        const savePath = await save({
          defaultPath: filename,
          filters: [{
            name: '图片文件',
            extensions: [filename.split('.').pop() || 'png']
          }]
        })
        
        if (savePath) {
          // 写入文件
          const { writeFile } = await import('@tauri-apps/plugin-fs')
          await writeFile(savePath, fileData)
          toast.success(`已保存到: ${savePath}`)
        }
      } catch (error) {
        console.error('保存文件失败:', error)
        toast.error('保存失败: ' + error.message)
      }
    }
    
    window.copyToClipboard = async (btn) => {
      const wrapper = btn.closest('.group')
      if (!wrapper) return
      
      const codeBlock = wrapper.querySelector('code')
      if (!codeBlock) return
      
      const text = codeBlock.innerText || codeBlock.textContent || ''
      const copyIcon = btn.querySelector('.lucide-copy')
      const checkIcon = btn.querySelector('.lucide-check')

      const finishSuccess = () => {
        if (copyIcon) copyIcon.classList.add('hidden')
        if (checkIcon) checkIcon.classList.remove('hidden')
        toast.success('已复制到剪贴板')
        setTimeout(() => {
          if (copyIcon) copyIcon.classList.remove('hidden')
          if (checkIcon) checkIcon.classList.add('hidden')
        }, 2000)
      }

      const copyWithClipboardApi = async () => {
        if (!navigator?.clipboard?.writeText) return false
        try {
          await navigator.clipboard.writeText(text)
          return true
        } catch (err) {
          return false
        }
      }

      const copyWithExecCommand = () => {
        try {
          const listener = (event) => {
            event.clipboardData?.setData('text/plain', text)
            event.preventDefault()
          }
          document.addEventListener('copy', listener, { once: true })
          const ok = document.execCommand('copy')
          document.removeEventListener('copy', listener)
          if (ok) return true
        } catch (err) {
          console.error('复制失败:', err)
        }
        return false
      }

      const copyWithTextarea = () => {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.setAttribute('readonly', '')
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        ta.style.top = '0'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        try {
          const ok = document.execCommand('copy')
          document.body.removeChild(ta)
          return ok
        } catch (err) {
          document.body.removeChild(ta)
          console.error('复制失败:', err)
          return false
        }
      }

      if (!text) {
        toast.error('复制失败')
        return
      }

      const ok = await copyWithClipboardApi() || copyWithExecCommand() || copyWithTextarea()
      if (ok) {
        finishSuccess()
      } else {
        toast.error('复制失败')
      }
    }
  }
  
  renderCharts()
  renderMermaid()
  loadLocalImages()
})

watch(() => props.content, async () => {
  await renderCharts()
  await renderMermaid()
  await loadLocalImages()
}, {flush: 'post'})

onUnmounted(() => {
  disposeCharts()
  revokeLocalImageObjectUrls()
})
</script>
