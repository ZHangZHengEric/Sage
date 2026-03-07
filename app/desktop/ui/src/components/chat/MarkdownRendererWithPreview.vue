<template>
  <div class="markdown-with-preview">
    <div ref="markdownRef">
      <MarkdownRenderer
        :content="content"
      />
    </div>
    <!-- 文件预览区域 - 根据检测到的文件路径动态生成 -->
    <div v-if="filePreviews.length > 0" class="file-previews-container">
      <template v-for="(fileInfo, index) in filePreviews" :key="fileInfo.id">
        <FilePreview
          :file-path="fileInfo.path"
          :auto-load="true"
          :default-expanded="true"
          class="my-2"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import FilePreview from './FilePreview.vue'

const props = defineProps({
  content: {
    type: String,
    default: ''
  }
})

// 检测内容中的可预览文件链接
const filePreviews = computed(() => {
  if (!props.content) return []

  const files = []
  const previewableExts = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'html', 'htm', 'md', 'markdown', 'excalidraw', 'txt', 'json', 'xml', 'yaml', 'yml', 'csv', 'js', 'ts', 'jsx', 'tsx', 'py', 'java', 'cpp', 'c', 'go', 'rs', 'css', 'scss', 'vue', 'php', 'rb', 'sql', 'sh', 'bash']

  // 辅助函数：检查并添加文件路径
  const checkAndAddFile = (path, index) => {
    const ext = path.split('.').pop().toLowerCase()

    if (previewableExts.includes(ext)) {
      let normalizedPath = path
      normalizedPath = normalizedPath.replace(/^file:\/\/\/?/i, '')
      try {
        normalizedPath = decodeURIComponent(normalizedPath)
      } catch (e) {}

      if (normalizedPath.startsWith('/')) {
        files.push({
          id: `preview-${index}-${normalizedPath}`,
          path: normalizedPath
        })
      }
    }
  }

  // 匹配 Markdown 格式的本地文件链接 [text](/path/to/file)
  const markdownRegex = /\[([^\]]*)\]\((\/(?:[^()]*|\([^)]*\))*)\)/g
  let match
  let counter = 0
  while ((match = markdownRegex.exec(props.content)) !== null) {
    checkAndAddFile(match[2], counter++)
  }

  // 匹配代码块中的文件路径 `/path/to/file`
  const codePathRegex = /`(\/[^`]+\.(?:pdf|png|jpg|jpeg|gif|webp|svg|html|htm|md|markdown|excalidraw|txt|json|xml|yaml|yml|csv|js|ts|jsx|tsx|py|java|cpp|c|go|rs|css|scss|vue|php|rb|sql|sh|bash))`/gi
  while ((match = codePathRegex.exec(props.content)) !== null) {
    checkAndAddFile(match[1], counter++)
  }

  // 匹配纯文本中的文件路径（以 / 开头，包含文件扩展名）
  const plainPathRegex = /(?:^|\s)(\/[^\s]+\.(?:pdf|png|jpg|jpeg|gif|webp|svg|html|htm|md|markdown|excalidraw|txt|json|xml|yaml|yml|csv|js|ts|jsx|tsx|py|java|cpp|c|go|rs|css|scss|vue|php|rb|sql|sh|bash))(?:\s|$)/gi
  while ((match = plainPathRegex.exec(props.content)) !== null) {
    checkAndAddFile(match[1], counter++)
  }

  return files
})

const markdownRef = ref(null)
</script>

<style scoped>
.markdown-with-preview {
  width: 100%;
}

.file-previews-container {
  width: 100%;
}
</style>
