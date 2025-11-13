<template>
  <div class="markdown-content" v-html="renderedContent"></div>
</template>

<script setup>
import {computed, nextTick, onMounted, watch} from 'vue'
import {marked} from 'marked'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'


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
  console.log("language", language, code.lang)
  // 获取代码文本，兼容不同版本的 marked
  let codeText = typeof code === 'string' ? code : code.text
  if (code.lang === 'echarts') {
    try {
      // 移除 option = 前缀和末尾的分号
      codeText = codeText.replace(/^[\s\S]*?=\s*/, '').trim()
      if (codeText.endsWith(';')) {
        codeText = codeText.slice(0, -1).trim()
      }
      const id = `chart-${Math.random().toString(36).substr(2, 9)}`
      const jsonStr = jsToJson(codeText)
      const option = JSON.parse(jsonStr)
      chartList.push({id, option})
      return `<div id="${id}" class="markdown-chart" style="width:100%; height:300px;"></div>`
    } catch (err) {
      console.error('ECharts 配置解析失败:', err)
      return `<pre style="color:red;">图表配置错误: ${err.message}</pre>`
    }
  }

  // 转义代码中的HTML特殊字符
  const escapedCode = escapeHtml(codeText)
  return `<pre><code class="language-${language || 'plaintext'}">${escapedCode}</code></pre>`
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

    return `<div class="markdown-image-container">
      <img${attrs} class="markdown-image">
      <button class="markdown-image-download" onclick="window.downloadMarkdownImage('${src}', '${filename}')" title="下载图片">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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
      return `<video controls class="markdown-video">
        <source src="${url}" type="video/mp4">
        您的浏览器不支持视频播放。
      </video>`
    }
    return match
  })

  // 然后处理直接的视频URL（不在链接标签中的）
  html = html.replace(/(?<!src="|href=")https?:\/\/[^\s<>"]+\.(mp4|webm|ogg|mov|avi|mkv)(?:\?[^\s<>"]*)?/gi, (match) => {
    return `<video controls class="markdown-video">
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

<style scoped>
.markdown-content {
  line-height: 1.6;
  color: inherit;
}

/* 全局样式，不使用scoped */
</style>

<style>
.markdown-content h1,
.markdown-content h2,
.markdown-content h3,
.markdown-content h4,
.markdown-content h5,
.markdown-content h6 {
  margin: 16px 0 8px 0;
  font-weight: 600;
  line-height: 1.4;
}

.markdown-content h1 {
  font-size: 1.5em;
  border-bottom: 1px solid #e1e5e9;
  padding-bottom: 8px;
}

.markdown-content h2 {
  font-size: 1.3em;
}

.markdown-content h3 {
  font-size: 1.2em;
}

.markdown-content h4,
.markdown-content h5,
.markdown-content h6 {
  font-size: 1.1em;
}

.markdown-content p {
  margin: 8px 0;
}

.markdown-content ul,
.markdown-content ol {
  margin: 8px 0;
  padding-left: 20px;
}

.markdown-content li {
  margin: 4px 0;
}

.markdown-content blockquote {
  margin: 12px 0;
  padding: 8px 16px;
  border-left: 4px solid #e1e5e9;
  background: #f8f9fa;
  color: #666;
}

.markdown-content code {
  background: #f1f3f4;
  padding: 2px 4px;
  border-radius: 3px;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.9em;
}

.markdown-content pre {
  background: #f8f9fa;
  border: 1px solid #e1e5e9;
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
  margin: 12px 0;
}

.markdown-content pre code {
  background: none;
  padding: 0;
  border-radius: 0;
  color: #1a202c;
}

.markdown-content a {
  color: #4facfe;
  text-decoration: none;
}

.markdown-content a:hover {
  text-decoration: underline;
}

.markdown-content .markdown-image-container {
  position: relative;
  display: inline-block;
  margin: 8px 0;
}

.markdown-content .markdown-image {
  max-width: 300px;
  height: auto;
  border-radius: 6px;
  display: block;
}

.markdown-content .markdown-image-download {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  border: none;
  border-radius: 4px;
  padding: 6px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.markdown-content .markdown-image-container:hover .markdown-image-download {
  opacity: 1;
}

.markdown-content .markdown-image-download:hover {
  background: rgba(0, 0, 0, 0.9);
}

.markdown-content .markdown-image-download svg {
  width: 16px;
  height: 16px;
}

.markdown-content table {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
}

.markdown-content th,
.markdown-content td {
  border: 1px solid #e1e5e9;
  padding: 8px 12px;
  text-align: left;
}

.markdown-content th {
  background: #f8f9fa;
  font-weight: 600;
}

.markdown-content strong {
  font-weight: 600;
}

.markdown-content em {
  font-style: italic;
}

.markdown-content del {
  text-decoration: line-through;
}

.markdown-content .markdown-video {
  max-width: 300px;
  height: auto;
  border-radius: 6px;
  margin: 12px 0;
  background: #000;
}

.markdown-content .markdown-chart {
  height: 300px !important;
}
</style>