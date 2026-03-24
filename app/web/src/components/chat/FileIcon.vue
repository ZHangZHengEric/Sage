<template>
  <div 
    class="file-icon inline-flex items-center gap-2 px-3 py-2 bg-muted/50 hover:bg-muted rounded-lg border border-border/50 cursor-pointer transition-colors group"
    @click="handleClick"
    :title="`查看文件: ${displayFileName}`"
  >
    <img v-if="iconType === 'image'" :src="iconSrc" class="w-5 h-5 object-contain" />
    <span v-else class="text-lg">{{ iconSrc }}</span>
    <span class="text-sm font-medium truncate max-w-[150px]">{{ displayFileName }}</span>
    <ExternalLink class="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ExternalLink } from 'lucide-vue-next'
import { useWorkbenchStore } from '../../stores/workbench.js'
import { usePanelStore } from '../../stores/panel.js'

import { getFileExtension, isImageFile, getFileIcon, getDisplayFileName } from '../../utils/fileIcons.js'

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
  return getDisplayFileName(props.filePath, props.fileName)
})

const fileExtension = computed(() => {
  return getFileExtension(props.filePath, displayFileName.value)
})

const iconType = computed(() => {
  return isImageFile(fileExtension.value) ? 'image' : 'emoji'
})

const iconSrc = computed(() => {
  // 如果是文件夹，返回文件夹图标
  if (props.isDirectory) {
    return '📁'
  }

  // 图片文件 - 使用文件路径作为图标
  if (iconType.value === 'image') {
    return props.filePath
  }

  return getFileIcon(fileExtension.value)
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
