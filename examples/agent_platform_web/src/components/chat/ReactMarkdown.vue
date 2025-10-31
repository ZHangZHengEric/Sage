<template>
  <div class="markdown-content" v-html="renderedContent"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

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

// 配置marked选项
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false
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
</style>