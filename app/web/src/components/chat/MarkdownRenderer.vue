<template>
  <div class="prose prose-sm dark:prose-invert max-w-none break-words" v-html="renderedContent"></div>
</template>

<script setup>
import {computed, nextTick, onMounted, watch} from 'vue'
import {marked} from 'marked'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'
import Prism from 'prismjs'
import 'prismjs/themes/prism-tomorrow.css'

// 基础依赖（必须按顺序加载）
import 'prismjs/components/prism-clike'
import 'prismjs/components/prism-markup'
import 'prismjs/components/prism-markup-templating'

// 常用语言
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
const renderer = new marked.Renderer()
renderer.code = (code, language) => {
  // 获取代码文本，兼容不同版本的 marked
  const codeText = typeof code === 'string' ? code : code.text
  // 优先从 token 对象中获取 lang，其次是 language 参数，最后默认为 plaintext
  // marked v5+ 传入的是 token 对象，lang 属性在对象中
  const rawLang = (typeof code === 'string' ? language : code.lang) || ''
  const lang = rawLang.split(/\s+/)[0] || 'plaintext'

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

  let highlighted = ''
  try {
    if (lang !== 'plaintext' && Prism.languages[lang]) {
      highlighted = Prism.highlight(codeText, Prism.languages[lang], lang)
    } else {
      highlighted = escapeHtml(codeText)
    }
  } catch (e) {
    console.warn('Prism highlight failed:', e)
    highlighted = escapeHtml(codeText)
  }

  return `<pre class="not-prose rounded-lg p-4 overflow-x-auto my-4 border language-${lang}"><code class="language-${lang} text-sm font-mono">${highlighted}</code></pre>`
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

// 检测视频链接的正则表达式
const videoExtensions = /\.(mp4|webm|ogg|mov|avi|mkv)$/i

// 检测图片链接的正则表达式
const imageExtensions = /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i

// 生成唯一ID
const generateId = () => Math.random().toString(36).substr(2, 9)

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
        // 如果fetch失败，尝试直接下载
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
    const imageId = generateId()
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

// 将视频链接转换为video标签
const convertVideoLinks = (html) => {
  // 首先处理链接标签中的视频URL
  html = html.replace(/<a[^>]*href="([^"]*)"[^>]*>([^<]*)<\/a>/g, (match, url, text) => {
    if (videoExtensions.test(url)) {
      return `<video controls class="w-full rounded-lg my-4 border bg-black/5">
        <source src="${url}" type="video/mp4">
        您的浏览器不支持视频播放。
      </video>`
    }
    return match
  })

  // 然后处理直接的视频URL（不在链接标签中的）
  html = html.replace(/(?<!src="|href=")https?:\/\/[^\s<>"]+\.(mp4|webm|ogg|mov|avi|mkv)(?:\?[^\s<>"]*)?/gi, (match) => {
    return `<video controls class="w-full rounded-lg my-4 border bg-black/5">
      <source src="${match}" type="video/mp4">
      您的浏览器不支持视频播放。
    </video>`
  })

  return html
}

// 设置全局下载函数
if (typeof window !== 'undefined') {
  window.downloadMarkdownImage = downloadImage
}

// 渲染Markdown内容
const renderedContent = computed(() => {
  if (!props.content) return ''

  try {
    // 使用marked解析Markdown
    chartList.length = 0

    let html = marked(props.content)

    // 转换视频链接
    html = convertVideoLinks(html)

    // 为图片添加下载按钮
    html = addImageDownloadButton(html)

    // 使用DOMPurify清理HTML，防止XSS攻击
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'u', 'del', 'code', 'pre',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'blockquote',
        'a', 'img',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'div', 'span', 'button', 'svg', 'path', 'polyline', 'line',
        'video', 'source'
      ],
      ALLOWED_ATTR: [
        'href', 'src', 'alt', 'title', 'class', 'id',
        'target', 'rel', 'controls', 'type', 'onclick',
        'width', 'height', 'viewBox', 'fill', 'stroke', 'stroke-width',
        'points', 'x1', 'y1', 'x2', 'y2', 'd'
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
  // 关键：等待 DOM 完全渲染，确保容器有宽高
  await new Promise(resolve => setTimeout(resolve, 200))

  chartList.forEach(({id, option}) => {
    const el = document.getElementById(id)
    console.log(`初始化图表 ${id}:`, {
      element: !!el,
      width: el?.clientWidth,
      height: el?.clientHeight
    })

    if (el && el.clientWidth > 0 && el.clientHeight > 0) {
      try {
        const chart = echarts.init(el)
        chart.setOption(option)
        console.log(`✓ 图表 ${id} 初始化成功`)
      } catch (err) {
        console.error(`✗ 图表 ${id} 初始化失败:`, err)
      }
    } else {
      console.warn(`✗ 图表容器 ${id} 未准备好`)
    }
  })
}

// 在内容变化后重渲染图表
onMounted(renderCharts)
watch(() => props.content, async () => {
  // 内容变化时，先等待 computed 更新，再渲染图表
  await renderCharts()
}, {flush: 'post'})
</script>
