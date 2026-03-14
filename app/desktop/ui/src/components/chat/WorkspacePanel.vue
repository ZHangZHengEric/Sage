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
      <!-- 拖拽提示 -->
      <div 
        v-if="isDraggingOver" 
        class="flex flex-col items-center justify-center py-8 text-primary"
      >
        <Upload class="w-12 h-12 mb-2" />
        <p class="text-sm font-medium">{{ t('workspace.dropHere') || '释放以上传文件或文件夹' }}</p>
      </div>
      
      <!-- 上传进度 -->
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
        <div v-if="hasValidFiles" class="flex flex-col gap-1">
          <WorkspaceFileTree
            v-for="node in fileTree"
            :key="node.path"
            :item="node"
            @download="handleDownload"
            @delete="handleDelete"
            @quote="handleQuote"
          />
        </div>
        <div v-else-if="!isDraggingOver && !uploading" class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <FolderOpen class="w-12 h-12 mb-2 opacity-50" />
          <p class="text-sm">{{ t('workspace.noFiles') }}</p>
          <p class="text-xs mt-1 opacity-70">{{ t('workspace.dragHint') || '拖拽文件或文件夹到此处' }}</p>
        </div>
      </div>
    </div>
  </ResizablePanel>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { FolderOpen, Upload } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import WorkspaceFileTree from './WorkspaceFileTree.vue'
import { ScrollArea } from '@/components/ui/scroll-area'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  },
  agentId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'downloadFile', 'deleteFile', 'quotePath', 'uploadFiles'])

const { t } = useLanguage()

const isDraggingOver = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadStatus = ref('')
const dropZoneRef = ref(null)

// 监听Tauri拖拽事件（桌面端）
let tauriDropListener = null

onMounted(() => {
  // 监听Tauri的文件拖拽事件
  tauriDropListener = (e) => {
    const files = e.detail
    if (files && files.length > 0) {
      handleTauriFiles(files)
    }
  }
  window.addEventListener('tauri-files-dropped', tauriDropListener)
})

onUnmounted(() => {
  if (tauriDropListener) {
    window.removeEventListener('tauri-files-dropped', tauriDropListener)
  }
})

// 处理Tauri拖拽的文件
const handleTauriFiles = async (filePaths) => {
  if (!props.agentId || filePaths.length === 0) return
  
  console.log('Handling Tauri files:', filePaths)
  
  // 将文件路径转换为文件对象
  const files = []
  
  for (const filePath of filePaths) {
    try {
      // 使用Tauri的fs API读取文件
      const { readFile } = await import('@tauri-apps/plugin-fs')
      const { basename } = await import('@tauri-apps/api/path')
      
      const fileName = await basename(filePath)
      const fileData = await readFile(filePath)
      
      // 创建File对象
      const file = new File([fileData], fileName, { type: 'application/octet-stream' })
      
      files.push({
        file,
        relativePath: fileName,
        sourcePath: filePath
      })
    } catch (error) {
      console.error('Failed to read file:', filePath, error)
    }
  }
  
  if (files.length > 0) {
    emit('uploadFiles', files)
  }
}

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
  
  // Sort function
  const sortNodes = (nodes) => {
    nodes.sort((a, b) => {
      // Directories first
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

// 拖拽事件处理
const handleDragEnter = (e) => {
  e.preventDefault()
  e.stopPropagation()
  console.log('DragEnter triggered', e.dataTransfer?.types)
  // 检查是否包含文件
  if (e.dataTransfer && e.dataTransfer.types) {
    // 兼容不同浏览器的类型检查
    const types = Array.from(e.dataTransfer.types)
    console.log('DataTransfer types:', types)
    if (types.includes('Files') || types.includes('application/x-moz-file')) {
      isDraggingOver.value = true
    }
  }
}

const handleDragOver = (e) => {
  e.preventDefault()
  e.stopPropagation()
  // 必须设置dropEffect才能触发drop事件
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'copy'
  }
}

const handleDragLeave = (e) => {
  e.preventDefault()
  e.stopPropagation()
  // 检查是否真的离开了元素（而不是进入了子元素）
  const rect = dropZoneRef.value?.getBoundingClientRect()
  const x = e.clientX
  const y = e.clientY
  
  // 如果鼠标位置还在元素范围内，不触发leave
  if (rect && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
    return
  }
  
  isDraggingOver.value = false
}

const handleDrop = async (e) => {
  e.preventDefault()
  e.stopPropagation()
  console.log('Drop triggered')
  isDraggingOver.value = false
  
  if (!props.agentId) {
    console.log('No agentId, skipping upload')
    return
  }
  
  // 尝试多种方式获取文件
  let files = []
  
  // 方式1: 使用dataTransfer.items (现代浏览器支持文件夹)
  const items = e.dataTransfer?.items
  if (items && items.length > 0) {
    console.log('Using items approach, count:', items.length)
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.()
      
      if (entry) {
        console.log('Entry found:', entry.name, 'isDirectory:', entry.isDirectory)
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
        // 回退到普通文件
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
  
  // 方式2: 使用dataTransfer.files (所有浏览器都支持，但不支持文件夹)
  if (files.length === 0) {
    const dtFiles = e.dataTransfer?.files
    if (dtFiles && dtFiles.length > 0) {
      console.log('Using files approach, count:', dtFiles.length)
      for (let i = 0; i < dtFiles.length; i++) {
        const file = dtFiles[i]
        files.push({
          file,
          relativePath: file.name,
          sourcePath: null
        })
      }
    }
  }
  
  console.log('Total files to upload:', files.length)
  if (files.length > 0) {
    emit('uploadFiles', files)
  }
}

// 递归遍历文件夹
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
        
        // 继续读取（某些浏览器一次只返回100个条目）
        await readEntries()
        resolve()
      })
    })
  }
  
  await readEntries()
}

// 从FileEntry获取File对象
const getFileFromEntry = (fileEntry) => {
  return new Promise((resolve) => {
    fileEntry.file((file) => {
      resolve(file)
    }, () => {
      resolve(null)
    })
  })
}

const handleDownload = (item) => {
  emit('downloadFile', item)
}

const handleDelete = (item) => {
  emit('deleteFile', item)
}

const handleQuote = (item) => {
  emit('quotePath', item.path)
}

// 设置上传状态（供父组件调用）
const setUploadStatus = (status, progress = 0) => {
  uploading.value = !!status
  uploadStatus.value = status || ''
  uploadProgress.value = progress
}

defineExpose({
  setUploadStatus
})
</script>
