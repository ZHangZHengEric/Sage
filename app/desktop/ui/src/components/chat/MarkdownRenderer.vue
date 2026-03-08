<template>
  <div class="prose prose-sm dark:prose-invert max-w-none break-words" v-html="renderedContent" @click="handleMarkdownClick"></div>
</template>

<script setup>
import {computed, nextTick, onMounted, watch} from 'vue'
import {marked} from 'marked'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'
import mermaid from 'mermaid'
import { open } from '@tauri-apps/plugin-shell'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypePrism from 'rehype-prism-plus'
import rehypeStringify from 'rehype-stringify'
import { visit } from 'unist-util-visit'
import { toast } from 'vue-sonner'

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
    <table class="w-full text-sm border-collapse border rounded-md">
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
    ? 'border px-4 py-2 text-left font-medium text-muted-foreground'
    : 'border px-4 py-2'
    
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
              'my-4',
              'p-4',
              'rounded-lg',
              'overflow-auto',
              'text-sm',
              'font-mono',
              'leading-relaxed',
              'bg-muted/50',
              'border',
              'border-border/50'
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
  return html.replace(/<img([^>]*src="([^"]*)"[^>]*)>/g, (match, attrs, src) => {
    const filename = src.split('/').pop().split('?')[0] || 'image'
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
  if (!path) return ''
  let normalized = String(path).trim()
  if (fileProtocolPattern.test(normalized)) {
    normalized = normalized.replace(/^file:\/\/\/?/i, '')
  }
  try {
    normalized = decodeURIComponent(normalized)
  } catch (error) {
    normalized = normalized.replace(/%20/g, ' ')
  }
  if (/^[a-zA-Z]:\//.test(normalized)) {
    return normalized
  }
  if (/^\/[a-zA-Z]:\//.test(normalized)) {
    return normalized.slice(1)
  }
  if (!normalized.startsWith('/') && unixAbsolutePathPattern.test(`/${normalized}`)) {
    return `/${normalized}`
  }
  return normalized
}

const isLocalAbsolutePath = (path) => {
  if (!path) return false
  const normalized = normalizeLocalPath(path)
  return unixAbsolutePathPattern.test(normalized) || windowsAbsolutePathPattern.test(normalized)
}

const toFileUrl = (localPath) => {
  if (windowsAbsolutePathPattern.test(localPath)) {
    return `file:///${encodeURI(localPath.replace(/\\/g, '/'))}`
  }
  return `file://${encodeURI(localPath)}`
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
  
  // 处理本地文件链接 - 将 Markdown 格式的本地文件链接转换为 HTML，避免 marked 解析问题
  // 匹配 [text](/path/to/file) 格式，路径可以包含括号
  processed = processed.replace(
    /\[([^\]]*)\]\((\/(?:[^()]*|\([^)]*\))*)\)/g,
    (match, text, path) => {
      // 检查是否是本地绝对路径
      if (isLocalAbsolutePath(path)) {
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

  // 处理 HTTP 文件链接
  processed = processed.replace(
    /(https?:\/\/[^\n\r"<>]+?\.(?:pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|tar|gz|bz2|txt|csv|json|xml|md|jpg|jpeg|png|gif|svg|webp|mp4|webm|mp3|wav))/gi,
    (match) => match.replace(/\s/g, '%20')
  )

  return processed
}

const renderedContent = computed(() => {
  if (!props.content) return ''

  try {
    chartList.length = 0
    mermaidList.length = 0
    excalidrawList.length = 0
    const preprocessed = preprocessContent(props.content)
    let html = marked(preprocessed)

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
const renderCharts = async () => {
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 200))

  chartList.forEach(({id, option}) => {
    const el = document.getElementById(id)
    if (el && el.clientWidth > 0 && el.clientHeight > 0) {
      try {
        const chart = echarts.init(el)
        chart.setOption(option)
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
  if (!isLocalAbsolutePath(localPath)) return
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
      const localPath = normalizeLocalPath(raw)
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
})

watch(() => props.content, async () => {
  await renderCharts()
  await renderMermaid()
}, {flush: 'post'})
</script>
