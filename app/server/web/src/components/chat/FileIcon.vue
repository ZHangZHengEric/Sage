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

import { getFileExtension, isImageFile, getFileIcon, getDisplayFileName, normalizeFilePath } from '../../utils/fileIcons.js'

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
  messageId: {
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
  const normalizedPath = normalizeFilePath(props.filePath)
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

  const targetByMessage = (workbenchStore.items || []).find(item => item?.stableKey === stableKey)
  if (targetByMessage?.sessionId) {
    workbenchStore.setSessionId(targetByMessage.sessionId, { autoJumpToLast: false })
    const index = (workbenchStore.filteredItems || []).findIndex(item => item?.id === targetByMessage.id)
    if (index !== -1) {
      workbenchStore.setCurrentIndex(index)
      return
    }
  }
  
  // 否则查找对应的文件项
  let index = (workbenchStore.filteredItems || []).findIndex(item => 
    item.type === 'file' && normalizeFilePath(item.data.filePath) === normalizedPath
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
      normalizeFilePath(item?.data?.filePath || item?.data?.path) === normalizedPath
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
