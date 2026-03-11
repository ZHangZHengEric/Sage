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

const handleClick = () => {
  // 先打开工作台
  panelStore.openWorkbench()
  
  // 如果指定了工作台项ID，直接跳转到该项
  if (props.workbenchItemId) {
    const index = workbenchStore.items.findIndex(item => item.id === props.workbenchItemId)
    if (index !== -1) {
      workbenchStore.setCurrentIndex(index)
      workbenchStore.setRealtime(false)
      return
    }
  }
  
  // 否则查找对应的文件项
  const index = workbenchStore.items.findIndex(item => 
    item.type === 'file' && item.data.filePath === props.filePath
  )
  
  if (index !== -1) {
    workbenchStore.setCurrentIndex(index)
    workbenchStore.setRealtime(false)
  } else {
    // 如果工作台中没有，添加并跳转
    workbenchStore.addItem({
      type: 'file',
      role: 'assistant',
      timestamp: Date.now(),
      data: {
        filePath: props.filePath,
        fileName: displayFileName.value
      }
    })
    workbenchStore.setRealtime(false)
  }
}
</script>

<style scoped>
.file-icon {
  max-width: 100%;
}
</style>
