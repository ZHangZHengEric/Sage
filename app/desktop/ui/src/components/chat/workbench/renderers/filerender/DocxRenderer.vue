<template>
  <div class="docx-renderer h-full overflow-auto bg-[#f0f0f0] dark:bg-[#1a1a1a]">
    <!-- 工具栏 -->
    <div class="docx-toolbar sticky top-0 z-10 flex items-center justify-between px-4 py-2 bg-white dark:bg-[#2d2d2d] border-b border-[#d1d1d1] dark:border-[#444]">
      <div class="flex items-center gap-2">
        <FileText class="w-4 h-4 text-[#4472c4]" />
        <span class="text-sm font-medium text-[#333] dark:text-[#ccc]">Word 文档</span>
      </div>
      <div class="flex items-center gap-2">
        <Button v-if="error" variant="outline" size="sm" @click="openFile">
          <ExternalLink class="w-3.5 h-3.5 mr-1" />
          打开文件
        </Button>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="flex items-center justify-center h-[calc(100%-40px)]">
      <div class="text-center">
        <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2 text-[#4472c4]" />
        <p class="text-sm text-[#666] dark:text-[#999]">正在解析 Word 文件...</p>
      </div>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="flex flex-col items-center justify-center h-[calc(100%-40px)] p-8">
      <FileText class="w-16 h-16 mb-3 opacity-30" />
      <p class="text-sm mb-1 text-[#666] dark:text-[#999]">无法预览 Word 文件</p>
      <p class="text-xs text-destructive mb-4">{{ error }}</p>
      <Button variant="outline" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        用系统应用打开
      </Button>
    </div>

    <!-- Word 文档内容 -->
    <div v-else class="docx-container">
      <div class="docx-page" v-html="content"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Loader2, FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import mammoth from 'mammoth'
import DOMPurify from 'dompurify'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  fileContent: {
    type: String,
    default: ''
  }
})

const loading = ref(false)
const error = ref('')
const content = ref('')

const base64ToUint8Array = (base64) => {
  const cleanBase64 = base64.replace(/[^A-Za-z0-9+/=]/g, '')
  
  try {
    const binaryString = atob(cleanBase64)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }
    return bytes
  } catch (e) {
    throw new Error('Base64 解码失败: ' + e.message)
  }
}

const loadDocx = async () => {
  if (!props.fileContent) {
    error.value = '文件内容为空'
    return
  }

  loading.value = true
  error.value = ''
  content.value = ''

  try {
    const bytes = base64ToUint8Array(props.fileContent)
    console.log('[DocxRenderer] File size:', bytes.length, 'bytes')

    // 使用 mammoth 转换 docx 到 HTML，添加样式映射
    const result = await mammoth.convertToHtml({
      arrayBuffer: bytes.buffer
    }, {
      styleMap: [
        // 标题样式映射
        "p[style-name='Title'] => h1",
        "p[style-name='Heading 1'] => h1",
        "p[style-name='Heading 2'] => h2",
        "p[style-name='Heading 3'] => h3",
        "p[style-name='Heading 4'] => h4",
        "p[style-name='Heading 5'] => h5",
        "p[style-name='Heading 6'] => h6",
        // 其他样式
        "p[style-name='Quote'] => blockquote",
        "p[style-name='Intense Quote'] => blockquote",
      ]
    })

    console.log('[DocxRenderer] Converted HTML length:', result.value?.length)
    console.log('[DocxRenderer] Converted HTML preview:', result.value?.substring(0, 200))

    // 如果转换结果为空，显示错误
    if (!result.value || result.value.trim().length === 0) {
      error.value = '文档内容为空或无法解析'
      loading.value = false
      return
    }

    // 清理 HTML，但保留 style 属性
    const sanitized = DOMPurify.sanitize(result.value, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'u', 'strike', 'sub', 'sup', 'b', 'i',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'table', 'thead', 'tbody', 'tr', 'td', 'th', 'caption',
        'a', 'img', 'span', 'div', 'blockquote', 'pre', 'code',
        'section', 'article', 'header', 'footer'
      ],
      ALLOWED_ATTR: [
        'href', 'src', 'alt', 'title', 'class', 'style', 'id',
        'colspan', 'rowspan', 'align', 'valign', 'width', 'height',
        'border', 'cellpadding', 'cellspacing'
      ],
      KEEP_CONTENT: true,
    })

    console.log('[DocxRenderer] Sanitized HTML length:', sanitized?.length)
    content.value = sanitized

    if (result.messages && result.messages.length > 0) {
      console.log('[DocxRenderer] Mammoth messages:', result.messages)
    }
  } catch (err) {
    console.error('[DocxRenderer] Loading error:', err)
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

const openFile = () => {
  if (props.filePath && window.__TAURI__) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

onMounted(() => {
  loadDocx()
})
</script>

<style scoped>
/* 容器样式 - 类似 Word 的灰色背景 */
.docx-renderer {
  font-family: 'Calibri', 'Microsoft YaHei', '微软雅黑', sans-serif;
}

/* 工具栏样式 */
.docx-toolbar {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

/* 文档容器 - 居中显示 */
.docx-container {
  padding: 20px;
  min-height: calc(100% - 40px);
}

/* Word 页面样式 - A4 纸张效果 */
.docx-page {
  max-width: 210mm;
  min-height: 297mm;
  margin: 0 auto;
  padding: 25mm;
  background: white;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.15);
  color: #000 !important;
  font-size: 11pt;
  line-height: 1.5;
}

/* 深色模式下的页面 */
:global(.dark) .docx-page {
  background: #2d2d2d;
  color: #e0e0e0 !important;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.5);
}

/* 段落样式 - Word 默认样式 */
.docx-page :deep(p) {
  margin: 0 0 8pt 0;
  text-align: left;
  text-indent: 0;
}

/* 标题样式 - Word 默认样式 */
.docx-page :deep(h1) {
  font-size: 16pt;
  font-weight: bold;
  margin: 12pt 0 6pt 0;
  color: inherit;
}

.docx-page :deep(h2) {
  font-size: 14pt;
  font-weight: bold;
  margin: 10pt 0 5pt 0;
  color: inherit;
}

.docx-page :deep(h3) {
  font-size: 12pt;
  font-weight: bold;
  margin: 8pt 0 4pt 0;
  color: inherit;
}

.docx-page :deep(h4),
.docx-page :deep(h5),
.docx-page :deep(h6) {
  font-size: 11pt;
  font-weight: bold;
  margin: 6pt 0 3pt 0;
  color: inherit;
}

/* 列表样式 - Word 默认 */
.docx-page :deep(ul),
.docx-page :deep(ol) {
  margin: 6pt 0;
  padding-left: 24pt;
}

.docx-page :deep(li) {
  margin: 2pt 0;
}

.docx-page :deep(ul) {
  list-style-type: disc;
}

.docx-page :deep(ol) {
  list-style-type: decimal;
}

/* 表格样式 - Word 默认表格样式 */
.docx-page :deep(table) {
  width: auto;
  border-collapse: collapse;
  margin: 6pt 0;
  font-size: 10pt;
}

.docx-page :deep(th),
.docx-page :deep(td) {
  border: 0.5pt solid #000;
  padding: 4pt 6pt;
  text-align: left;
  vertical-align: top;
}

:global(.dark) .docx-page :deep(th),
:global(.dark) .docx-page :deep(td) {
  border-color: #666;
}

.docx-page :deep(th) {
  background-color: #f0f0f0;
  font-weight: bold;
}

:global(.dark) .docx-page :deep(th) {
  background-color: #3d3d3d;
}

/* 强调样式 */
.docx-page :deep(strong),
.docx-page :deep(b) {
  font-weight: bold;
}

.docx-page :deep(em),
.docx-page :deep(i) {
  font-style: italic;
}

.docx-page :deep(u) {
  text-decoration: underline;
}

.docx-page :deep(strike),
.docx-page :deep(s) {
  text-decoration: line-through;
}

.docx-page :deep(sup) {
  vertical-align: super;
  font-size: smaller;
}

.docx-page :deep(sub) {
  vertical-align: sub;
  font-size: smaller;
}

/* 链接样式 */
.docx-page :deep(a) {
  color: #0563c1;
  text-decoration: underline;
}

:global(.dark) .docx-page :deep(a) {
  color: #4a9eff;
}

/* 图片样式 */
.docx-page :deep(img) {
  max-width: 100%;
  height: auto;
  display: inline-block;
}

/* 代码和预格式化文本 */
.docx-page :deep(pre) {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 10pt;
  background: #f5f5f5;
  padding: 6pt;
  margin: 6pt 0;
  border: 0.5pt solid #ddd;
  white-space: pre-wrap;
  word-wrap: break-word;
}

:global(.dark) .docx-page :deep(pre) {
  background: #1e1e1e;
  border-color: #444;
}

.docx-page :deep(code) {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 10pt;
  background: #f5f5f5;
  padding: 1pt 3pt;
}

:global(.dark) .docx-page :deep(code) {
  background: #1e1e1e;
}

/* 引用块 */
.docx-page :deep(blockquote) {
  margin: 6pt 0 6pt 24pt;
  padding: 0;
  border-left: none;
  font-style: italic;
  color: #555;
}

:global(.dark) .docx-page :deep(blockquote) {
  color: #aaa;
}

/* 分页符 */
.docx-page :deep(.page-break) {
  page-break-after: always;
  border-bottom: 1px dashed #ccc;
  margin: 12pt 0;
}

/* 水平线 */
.docx-page :deep(hr) {
  border: none;
  border-top: 0.5pt solid #000;
  margin: 8pt 0;
}

:global(.dark) .docx-page :deep(hr) {
  border-top-color: #666;
}

/* 打印样式 */
@media print {
  .docx-toolbar {
    display: none;
  }
  
  .docx-container {
    padding: 0;
    background: white;
  }
  
  .docx-page {
    box-shadow: none;
    max-width: none;
    padding: 20mm;
  }
}
</style>
