<template>
  <ResizablePanel
    :title="t('workspace.title')"
    :badge="workspaceFiles?.length || 0"
    size="large"
    @close="$emit('close')"
  >
    <template #icon>
      <FolderOpen class="w-4 h-4 text-muted-foreground" />
    </template>

    <div
      ref="dropZoneRef"
      class="h-full overflow-y-auto p-4 space-y-4 workspace-drop-zone"
      :class="{
        'bg-primary/5 border-2 border-dashed border-primary/50 rounded-lg': isDraggingOver
      }"
      @dragenter="handleDragEnter"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
    >
      <div
        v-if="isDraggingOver"
        class="flex flex-col items-center justify-center py-8 text-primary"
      >
        <Upload class="w-12 h-12 mb-2" />
        <p class="text-sm font-medium">{{ t('workspace.dropHere') }}</p>
      </div>

      <div v-if="uploading" class="space-y-2">
        <div class="flex items-center justify-between text-sm">
          <span class="text-muted-foreground">{{ uploadStatus }}</span>
          <span class="text-primary">{{ uploadProgress }}%</span>
        </div>
        <div class="h-2 bg-muted rounded-full overflow-hidden">
          <div
            class="h-full bg-primary transition-all duration-300"
            :style="{ width: `${uploadProgress}%` }"
          ></div>
        </div>
      </div>

      <div class="space-y-1">
        <div v-if="isLoading && !isDraggingOver && !uploading" class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <FolderOpen class="w-12 h-12 mb-2 opacity-50 animate-pulse" />
          <p class="text-sm">{{ t('workspace.loading') }}</p>
        </div>
        <div v-else-if="hasValidFiles" class="flex flex-col gap-1">
          <WorkspaceFileTree
            v-for="node in fileTree"
            :key="node.path"
            :item="node"
            @download="handleDownload"
            @delete="handleDelete"
            @quote="handleQuote"
            @view="handleView"
          />
        </div>
        <div v-else-if="!isDraggingOver && !uploading" class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <FolderOpen class="w-12 h-12 mb-2 opacity-50" />
          <p class="text-sm">{{ t('workspace.noFiles') }}</p>
          <p class="text-xs mt-1 opacity-70">{{ t('workspace.dragHint') }}</p>
        </div>
      </div>
    </div>
  </ResizablePanel>

  <Dialog v-model:open="previewOpen">
    <DialogContent class="max-w-[90vw] h-[85vh] p-0 overflow-hidden">
      <FileRenderer
        v-if="previewItem"
        :file-path="previewItem.path"
        :file-name="previewItem.name"
        :item="previewRendererItem"
        :dialog-mode="true"
      />
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { FolderOpen, Upload } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import WorkspaceFileTree from './WorkspaceFileTree.vue'
import FileRenderer from './workbench/renderers/FileRenderer.vue'
import { Dialog, DialogContent } from '@/components/ui/dialog'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  agentId: {
    type: String,
    default: ''
  },
  sessionId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'downloadFile', 'deleteFile', 'quotePath', 'uploadFiles'])

const { t } = useLanguage()
const previewOpen = ref(false)
const previewItem = ref(null)
const isDraggingOver = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadStatus = ref('')
const dropZoneRef = ref(null)

const hasValidFiles = computed(() => {
  return props.workspaceFiles && props.workspaceFiles.length > 0
})

const fileTree = computed(() => {
  if (!props.workspaceFiles || props.workspaceFiles.length === 0) return []

  const root = []
  const map = {}
  const hasBackslash = props.workspaceFiles.some(f => f.path.includes('\\'))
  const separator = hasBackslash ? '\\' : '/'

  props.workspaceFiles.forEach(file => {
    map[file.path] = { ...file, children: [] }
  })

  props.workspaceFiles.forEach(file => {
    const node = map[file.path]
    const parts = file.path.split(/[/\\]/)
    if (parts.length > 1) {
      const parentPath = parts.slice(0, -1).join(separator)
      if (map[parentPath]) {
        map[parentPath].children.push(node)
      } else {
        root.push(node)
      }
    } else {
      root.push(node)
    }
  })

  const sortNodes = (nodes) => {
    nodes.sort((a, b) => {
      if (a.is_directory !== b.is_directory) {
        return a.is_directory ? -1 : 1
      }
      return a.name.localeCompare(b.name)
    })
    nodes.forEach(node => {
      if (node.children.length > 0) sortNodes(node.children)
    })
  }

  sortNodes(root)
  return root
})

const handleDownload = (item) => {
  emit('downloadFile', item)
}

const handleDelete = (item) => {
  emit('deleteFile', item)
}

const handleQuote = (item) => {
  emit('quotePath', item.path)
}

const previewRendererItem = computed(() => {
  if (!previewItem.value) return null
  return {
    ...previewItem.value,
    agentId: props.agentId,
    sessionId: props.sessionId,
    role: 'assistant',
    timestamp: Date.now()
  }
})

const handleView = (item) => {
  if (!item || item.is_directory) return
  previewItem.value = item
  previewOpen.value = true
}

const getFileFromEntry = (fileEntry) => {
  return new Promise((resolve) => {
    fileEntry.file((file) => {
      resolve(file)
    }, () => {
      resolve(null)
    })
  })
}

const traverseDirectory = async (dirEntry, files, path) => {
  const dirReader = dirEntry.createReader()
  const readEntries = () => {
    return new Promise((resolve) => {
      dirReader.readEntries(async (entries) => {
        if (entries.length === 0) {
          resolve()
          return
        }
        for (const entry of entries) {
          const newPath = path ? `${path}/${entry.name}` : entry.name
          if (entry.isDirectory) {
            await traverseDirectory(entry, files, newPath)
          } else if (entry.isFile) {
            const file = await getFileFromEntry(entry)
            if (file) {
              files.push({
                file,
                relativePath: newPath,
                sourcePath: null
              })
            }
          }
        }
        await readEntries()
        resolve()
      })
    })
  }
  await readEntries()
}

const handleDragEnter = (e) => {
  e.preventDefault()
  e.stopPropagation()
  if (e.dataTransfer && e.dataTransfer.types) {
    const types = Array.from(e.dataTransfer.types)
    if (types.includes('Files') || types.includes('application/x-moz-file')) {
      isDraggingOver.value = true
    }
  }
}

const handleDragOver = (e) => {
  e.preventDefault()
  e.stopPropagation()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'copy'
  }
}

const handleDragLeave = (e) => {
  e.preventDefault()
  e.stopPropagation()
  const rect = dropZoneRef.value?.getBoundingClientRect()
  const x = e.clientX
  const y = e.clientY
  if (rect && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
    return
  }
  isDraggingOver.value = false
}

const handleDrop = async (e) => {
  e.preventDefault()
  e.stopPropagation()
  isDraggingOver.value = false
  if (!props.agentId) return

  const files = []
  const items = e.dataTransfer?.items
  if (items && items.length > 0) {
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.()
      if (entry) {
        if (entry.isDirectory) {
          await traverseDirectory(entry, files, '')
        } else if (entry.isFile) {
          const file = await getFileFromEntry(entry)
          if (file) {
            files.push({
              file,
              relativePath: file.name,
              sourcePath: null
            })
          }
        }
      } else {
        const file = item.getAsFile()
        if (file) {
          files.push({
            file,
            relativePath: file.name,
            sourcePath: null
          })
        }
      }
    }
  }

  if (files.length === 0) {
    const dtFiles = e.dataTransfer?.files
    if (dtFiles && dtFiles.length > 0) {
      for (let i = 0; i < dtFiles.length; i++) {
        files.push({
          file: dtFiles[i],
          relativePath: dtFiles[i].name,
          sourcePath: null
        })
      }
    }
  }

  if (files.length > 0) {
    emit('uploadFiles', files)
  }
}

const setUploadStatus = (status, progress = 0) => {
  uploading.value = !!status
  uploadStatus.value = status || ''
  uploadProgress.value = progress
}

defineExpose({
  setUploadStatus
})
</script>
