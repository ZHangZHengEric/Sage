<template>
  <div class="prose prose-sm dark:prose-invert max-w-none break-words" v-html="renderedContent"></div>
</template>

<script setup>
import {computed, nextTick, onMounted, watch} from 'vue'
import {marked} from 'marked'
import DOMPurify from 'dompurify'
import * as echarts from 'echarts'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypePrism from 'rehype-prism-plus'
import rehypeStringify from 'rehype-stringify'
import { visit } from 'unist-util-visit'
import { toast } from 'vue-sonner'

// 常用语言高亮样式
import 'prismjs/themes/prism-tomorrow.css' 

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

// Rehype 插件：代码块包装（添加语言标签和复制按钮）
const rehypeCodeBlockWrapper = () => {
  return (tree) => {
    visit(tree, 'element', (node, index, parent) => {
      // Rehype Prism Plus 可能会修改 pre/code 的结构
      // 它通常保持 pre > code 的结构，但 code 内部会有 span
      // 我们需要找到 pre 元素，并且它包含一个 code 元素
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
          
          // 如果 code 上没找到，有时 rehype-prism-plus 可能会把 class 移到 pre 上（取决于配置，默认通常在 code 上）
          if (lang === 'text' && node.properties && node.properties.className) {
             const classes = Array.isArray(node.properties.className) 
              ? node.properties.className 
              : [node.properties.className]
            
            const langClass = classes.find(c => String(c).startsWith('language-'))
            if (langClass) {
              lang = String(langClass).replace('language-', '')
            }
          }

          // SVG Icons AST
          const copyIcon = {
            type: 'element',
            tagName: 'svg',
            properties: {
              xmlns: "http://www.w3.org/2000/svg",
              width: "14",
              height: "14",
              viewBox: "0 0 24 24",
              fill: "none",
              stroke: "currentColor",
              "stroke-width": "2",
              "stroke-linecap": "round",
              "stroke-linejoin": "round",
              class: "lucide lucide-copy"
            },
            children: [
              { type: 'element', tagName: 'rect', properties: { width: "14", height: "14", x: "8", y: "8", rx: "2", ry: "2" }, children: [] },
              { type: 'element', tagName: 'path', properties: { d: "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" }, children: [] }
            ]
          }

          const checkIcon = {
             type: 'element',
             tagName: 'svg',
             properties: {
               xmlns: "http://www.w3.org/2000/svg",
               width: "14",
               height: "14",
               viewBox: "0 0 24 24",
               fill: "none",
               stroke: "currentColor",
               "stroke-width": "2",
               "stroke-linecap": "round",
               "stroke-linejoin": "round",
               class: "lucide lucide-check hidden" // 默认隐藏
             },
             children: [
                { type: 'element', tagName: 'polyline', properties: { points: "20 6 9 17 4 12" }, children: [] }
             ]
          }

          // 包装结构
          const wrapper = {
            type: 'element',
            tagName: 'div',
            properties: {
              className: ['relative', 'group', 'my-4', 'rounded-lg', 'border', 'bg-[#2b2b2b]', 'border-zinc-700']
            },
            children: [
              // 顶部栏
              {
                type: 'element',
                tagName: 'div',
                properties: {
                  className: ['flex', 'items-center', 'justify-between', 'px-3', 'py-2', 'bg-[#383838]', 'rounded-t-lg', 'border-b', 'border-zinc-600']
                },
                children: [
                  // 语言标签
                  {
                    type: 'element',
                    tagName: 'span',
                    properties: {
                      className: ['text-xs', 'font-medium', 'text-zinc-300', 'uppercase']
                    },
                    children: [{ type: 'text', value: lang }]
                  },
                  // 复制按钮
                  {
                    type: 'element',
                    tagName: 'button',
                    properties: {
                      className: ['copy-btn', 'p-1.5', 'hover:bg-zinc-600', 'rounded-md', 'transition-colors', 'text-zinc-300', 'hover:text-zinc-50', 'flex', 'items-center', 'gap-1'],
                      title: 'Copy code',
                      onclick: 'window.copyToClipboard(this)'
                    },
                    children: [
                      copyIcon,
                      checkIcon
                    ]
                  }
                ]
              },
              // 原 pre 元素，修改样式
              {
                ...node,
                properties: {
                  ...node.properties,
                  className: [...(node.properties.className || []), '!my-0', '!rounded-t-none', '!border-0', '!bg-transparent']
                }
              }
            ]
          }

          parent.children[index] = wrapper
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

      return `
        <a
          href="${href.replace(/ /g, '%20')}"
          download="${filename}"
          target="_blank"
          rel="noopener"
          class="text-primary underline underline-offset-4 hover:opacity-80 inline-flex items-center gap-1"
        >
          ${filename}
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

const preprocessContent = (content) => {
  if (!content) return ''
  return content.replace(
    /(https?:\/\/[^\n\r"<>)]+?\.(?:pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|7z|tar|gz|bz2|txt|csv|json|xml|md|jpg|jpeg|png|gif|svg|webp|mp4|webm|mp3|wav))/gi,
    (match) => match.replace(/\s/g, '%20')
  )
}

const renderedContent = computed(() => {
  if (!props.content) return ''

  try {
    chartList.length = 0
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

// Global functions setup
onMounted(() => {
  if (typeof window !== 'undefined') {
    window.downloadMarkdownImage = downloadImage
    
    window.copyToClipboard = (btn) => {
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

      const fallbackCopy = () => {
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
          if (ok) {
            finishSuccess()
          } else {
            toast.error('复制失败')
          }
        } catch (err) {
          document.body.removeChild(ta)
          console.error('复制失败:', err)
          toast.error('复制失败')
        }
      }

      if (navigator?.clipboard?.writeText && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
          finishSuccess()
        }).catch(() => {
          fallbackCopy()
        })
        return
      }

      fallbackCopy()
    }
  }
  
  renderCharts()
})

watch(() => props.content, async () => {
  await renderCharts()
}, {flush: 'post'})
</script>
