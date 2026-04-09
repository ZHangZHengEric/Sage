<template>
  <div class="markdown-with-preview">
    <div ref="markdownRef">
      <MarkdownRenderer
        :content="content"
        :compact="compact"
      />
    </div>
    <!-- 文件图标区域 - 显示检测到的文件链接为图标 -->
    <div v-if="fileIcons.length > 0" class="file-icons-container flex flex-wrap gap-2 mt-3">
      <FileIcon
        v-for="(fileInfo, index) in fileIcons"
        :key="fileInfo.id"
        :file-path="fileInfo.path"
        :file-name="fileInfo.name"
        :message-id="messageId"
        :is-directory="fileInfo.isDirectory"
        class="my-1"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import FileIcon from './FileIcon.vue'

const props = defineProps({
  content: {
    type: String,
    default: ''
  },
  compact: {
    type: Boolean,
    default: false
  },
  messageId: {
    type: String,
    default: ''
  }
})

// 检测内容中的文件链接
const fileIcons = computed(() => {
  if (!props.content) return []

  const files = []
  const seenPaths = new Set()

  // 辅助函数：规范化路径
  const normalizePath = (path) => {
    let normalizedPath = path
    // 支持 file:// 协议的路径
    if (normalizedPath.startsWith('file://')) {
      normalizedPath = normalizedPath.replace(/^file:\/\/\/?/i, '/')
    }
    try {
      normalizedPath = decodeURIComponent(normalizedPath)
    } catch (e) {}
    return normalizedPath
  }

  // 匹配 Markdown 格式的本地文件链接 [text](path)
  const markdownRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match
  let counter = 0

  while ((match = markdownRegex.exec(props.content)) !== null) {
    let path = match[2]
    const name = match[1]
    path = normalizePath(path)

    // 检查是否是本地绝对路径，且不是文件夹
    if (path.startsWith('/') && !seenPaths.has(path) && !path.endsWith('/')) {
      seenPaths.add(path)
      files.push({
        id: `file-${counter++}-${path}`,
        path: path,
        name: name
      })
    }
  }

  return files
})

const markdownRef = ref(null)
</script>

<style scoped>
.markdown-with-preview {
  width: 100%;
}

.file-icons-container {
  width: 100%;
}
</style>
