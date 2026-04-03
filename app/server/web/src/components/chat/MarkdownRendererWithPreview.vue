<template>
  <div class="markdown-with-preview">
    <div ref="markdownRef">
      <MarkdownRenderer
        :content="content"
        :components="components"
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
import { normalizeFilePath } from '@/utils/fileIcons.js'

const props = defineProps({
  content: {
    type: [String, Number, Boolean, Object, Array],
    default: ''
  },
  components: {
    type: Object,
    default: () => ({})
  },
  compact: {
    type: Boolean,
    default: false
  }
})

// 检测内容中的文件链接
const fileIcons = computed(() => {
  if (!props.content) return []

  let content = props.content
  if (typeof content !== 'string') {
    if (Array.isArray(content)) {
      content = content
        .map(item => {
          if (typeof item === 'string') return item
          if (item?.text) return item.text
          if (item?.content) return item.content
          return ''
        })
        .filter(Boolean)
        .join('\n')
    } else if (typeof content === 'object') {
      content = content.text || content.content || content.message || ''
    } else {
      content = String(content)
    }
  }

  const files = []
  const seenPaths = new Set()

  // 匹配 Markdown 格式的本地文件链接 [text](path)
  const markdownRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match
  let counter = 0

  while ((match = markdownRegex.exec(content)) !== null) {
    let path = match[2]
    const name = match[1]
    path = normalizeFilePath(path)

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
