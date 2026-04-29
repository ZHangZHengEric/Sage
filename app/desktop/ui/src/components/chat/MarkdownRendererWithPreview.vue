<template>
  <div class="markdown-with-preview">
    <div ref="markdownRef">
      <MarkdownRenderer
        :content="content"
        :compact="compact"
        :agent-id="agentId"
      />
    </div>
    <div v-if="fileIcons.length > 0" class="file-icons-container flex flex-wrap gap-2 mt-3">
      <FileIcon
        v-for="fileInfo in fileIcons"
        :key="fileInfo.id"
        :file-path="fileInfo.path"
        :file-name="fileInfo.name"
        :message-id="messageId"
        :is-directory="fileInfo.isDirectory"
        :agent-id="agentId"
        class="my-1"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import FileIcon from './FileIcon.vue'
import { isAbsoluteLocalPath, isRelativeWorkspacePath, normalizeFileReference, resolveAgentWorkspacePath } from '@/utils/agentWorkspacePath'

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
  },
  agentId: {
    type: String,
    default: ''
  }
})

const markdownRef = ref(null)
const resolvedFileIcons = ref([])
const fileIcons = computed(() => resolvedFileIcons.value)

const collectFileIcons = async () => {
  if (!props.content) {
    resolvedFileIcons.value = []
    return
  }

  const files = []
  const seenPaths = new Set()
  const markdownRegex = /\[([^\]]+)\]\(([^)]+)\)/g
  let match
  let counter = 0

  while ((match = markdownRegex.exec(props.content)) !== null) {
    const name = match[1]
    const rawPath = normalizeFileReference(match[2])
    const isWorkspaceRelative = !!props.agentId && isRelativeWorkspacePath(rawPath)

    if ((!isAbsoluteLocalPath(rawPath) && !isWorkspaceRelative) || rawPath.endsWith('/')) {
      continue
    }

    const resolvedPath = isWorkspaceRelative
      ? await resolveAgentWorkspacePath(rawPath, props.agentId)
      : rawPath

    if (!resolvedPath || seenPaths.has(resolvedPath)) continue

    seenPaths.add(resolvedPath)
    files.push({
      id: `file-${counter++}-${resolvedPath}`,
      path: resolvedPath,
      name
    })
  }

  resolvedFileIcons.value = files
}

watch(
  () => [props.content, props.agentId],
  () => {
    collectFileIcons()
  },
  { immediate: true }
)
</script>

<style scoped>
.markdown-with-preview {
  width: 100%;
}

.file-icons-container {
  width: 100%;
}
</style>
