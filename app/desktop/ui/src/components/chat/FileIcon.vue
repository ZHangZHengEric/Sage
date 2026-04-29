<template>
  <div 
    class="file-icon inline-flex items-center gap-2 px-3 py-2 bg-muted/50 hover:bg-muted rounded-lg border border-border/50 cursor-pointer transition-colors group"
    @click="handleClick"
    :title="`查看文件: ${displayFileName}`"
  >
    <span class="text-lg">{{ iconSrc }}</span>
    <span class="text-sm font-medium truncate max-w-[150px]">{{ displayFileName }}</span>
    <ExternalLink class="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ExternalLink } from 'lucide-vue-next'
import { useWorkbenchStore } from '../../stores/workbench.js'
import { usePanelStore } from '../../stores/panel.js'
import { resolveAgentWorkspacePath } from '@/utils/agentWorkspacePath'

const props = defineProps({
  filePath: {
    type: String,
    required: true
  },
  fileName: {
    type: String,
    default: ''
  },
  // 可选：指定要跳转的工作台项ID
  workbenchItemId: {
    type: String,
    default: ''
  },
  // 当前文件链接所在消息ID，用于精确定位对应的工作台项
  messageId: {
    type: String,
    default: ''
  },
  agentId: {
    type: String,
    default: ''
  },
  // 是否是文件夹
  isDirectory: {
    type: Boolean,
    default: false
  }
})

const workbenchStore = useWorkbenchStore()
const panelStore = usePanelStore()

const displayFileName = computed(() => {
  return props.fileName || props.filePath.split('/').pop() || 'file'
})

const fileExtension = computed(() => {
  const name = displayFileName.value
  const match = name.match(/\.([^.]+)$/)
  return match ? match[1].toLowerCase() : ''
})

const iconType = computed(() => {
  const ext = fileExtension.value
  const imageExts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico']
  if (imageExts.includes(ext)) return 'image'
  return 'emoji'
})

const iconSrc = computed(() => {
  // 如果是文件夹，返回文件夹图标
  if (props.isDirectory) {
    return '📁'
  }

  const ext = fileExtension.value

  // 使用 emoji 图标（所有文件类型都使用 emoji）
  const iconMap = {
    // Microsoft Office
    'doc': '📘', 'docx': '📘',
    'xls': '📗', 'xlsx': '📗', 'csv': '📗',
    'ppt': '📙', 'pptx': '📙',

    // PDF
    'pdf': '📕',

    // 图片
    'png': '🖼️', 'jpg': '🖼️', 'jpeg': '🖼️', 'gif': '🖼️',
    'webp': '🖼️', 'svg': '🎨', 'ico': '🎨',

    // 代码文件
    'html': '🌐', 'htm': '🌐',
    'css': '🎨', 'scss': '🎨', 'less': '🎨',
    'js': '📜', 'ts': '📜', 'jsx': '📜', 'tsx': '📜',
    'vue': '💚', 'svelte': '🧡',
    'py': '🐍', 'ipynb': '🐍',
    'java': '☕', 'class': '☕',
    'cpp': '⚙️', 'c': '⚙️', 'h': '⚙️',
    'go': '🐹', 'rs': '🦀',
    'rb': '💎', 'php': '🐘',
    'swift': '🐦', 'kt': '🎯',
    'sql': '🗄️',

    // 数据格式
    'json': '📋', 'xml': '📋', 'yaml': '📋', 'yml': '📋',

    // 文本
    'md': '📝', 'markdown': '📝',
    'txt': '📃', 'log': '📃',

    // 脚本
    'sh': '🔧', 'bash': '🔧', 'zsh': '🔧', 'ps1': '🔧',

    // 特殊
    'excalidraw': '✏️',
    'drawio': '📊',

    // 压缩包
    'zip': '📦', 'rar': '📦', '7z': '📦', 'tar': '📦', 'gz': '📦',

    // 可执行
    'exe': '⚡', 'dmg': '🍎', 'app': '🍎',

    // 音频视频
    'mp3': '🎵', 'mp4': '🎬', 'wav': '🎵', 'avi': '🎬', 'mov': '🎬'
  }

  return iconMap[ext] || '📎'
})

const handleClick = async () => {
  const normalizePath = (path) => {
    if (!path) return ''
    let normalized = path
    try {
      normalized = decodeURIComponent(normalized).trim()
    } catch (e) {}
    if (normalized.startsWith('`') && normalized.endsWith('`')) {
      normalized = normalized.slice(1, -1)
    }
    if (normalized.startsWith('/sage-workspace/')) {
      normalized = normalized.replace('/sage-workspace/', '/')
    }
    if (normalized.startsWith('file://')) {
      normalized = normalized.replace(/^file:\/\/\/?/i, '/')
    }
    return normalized
  }

  const resolvedFilePath = await resolveAgentWorkspacePath(props.filePath, props.agentId)
  const normalizedPath = normalizePath(resolvedFilePath)
  const stableKey = props.messageId
    ? `file:${props.messageId}:${normalizedPath}`
    : `file:${normalizedPath}`

  // 先打开工作台
  panelStore.openWorkbench()
  // 点击历史项时，先关闭实时，避免被流式新增项拉回最后
  workbenchStore.setRealtime(false)
  
  // 如果指定了工作台项ID，直接跳转到该项
  if (props.workbenchItemId) {
    let target = (workbenchStore.filteredItems || []).find(item => item?.id === props.workbenchItemId)
    if (!target) {
      target = (workbenchStore.items || []).find(item => item?.id === props.workbenchItemId)
      if (target?.sessionId) {
        workbenchStore.setSessionId(target.sessionId, { autoJumpToLast: false })
      }
    }
    if (target) {
      const index = (workbenchStore.filteredItems || []).findIndex(item => item?.id === target.id)
      if (index !== -1) {
        workbenchStore.setCurrentIndex(index)
      }
      return
    }
  }

  // 优先按 messageId + path 精确定位
  const targetByMessage = (workbenchStore.items || []).find(item => item?.stableKey === stableKey)
  if (targetByMessage?.sessionId) {
    workbenchStore.setSessionId(targetByMessage.sessionId, { autoJumpToLast: false })
    const index = (workbenchStore.filteredItems || []).findIndex(item => item?.id === targetByMessage.id)
    if (index !== -1) {
      workbenchStore.setCurrentIndex(index)
      return
    }
  }

  // 兜底：当前会话中按路径匹配
  let index = (workbenchStore.filteredItems || []).findIndex(item =>
    item?.type === 'file' &&
    normalizePath(item?.data?.filePath || item?.data?.path) === normalizedPath
  )
  if (index !== -1) {
    workbenchStore.setCurrentIndex(index)
    return
  }

  // 再兜底：全局按路径找最后一个同路径文件项，并切换到对应会话
  const globalSamePath = [...(workbenchStore.items || [])]
    .reverse()
    .find(item =>
      item?.type === 'file' &&
      normalizePath(item?.data?.filePath || item?.data?.path) === normalizedPath
    )
  if (globalSamePath?.sessionId) {
    workbenchStore.setSessionId(globalSamePath.sessionId, { autoJumpToLast: false })
    index = (workbenchStore.filteredItems || []).findIndex(item => item?.id === globalSamePath.id)
    if (index !== -1) {
      workbenchStore.setCurrentIndex(index)
      return
    }
  }

  // 如果工作台中没有，添加并跳转到新建项
  const createdItem = workbenchStore.addItem({
    type: 'file',
    role: 'assistant',
    timestamp: Date.now(),
    messageId: props.messageId || null,
    data: {
      filePath: normalizedPath,
      fileName: displayFileName.value
    }
  })
  if (createdItem?.id) {
    const createdIndex = (workbenchStore.filteredItems || []).findIndex(item => item?.id === createdItem.id)
    if (createdIndex !== -1) {
      workbenchStore.setCurrentIndex(createdIndex)
    }
  }
}
</script>

<style scoped>
.file-icon {
  max-width: 100%;
}
</style>
