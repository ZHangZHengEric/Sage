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
    
    <div class="h-full overflow-y-auto p-4 space-y-4">
      <div class="space-y-1">
        <div v-if="hasValidFiles" class="flex flex-col gap-1">
          <WorkspaceFileTree 
            v-for="node in fileTree" 
            :key="node.path" 
            :item="node" 
            @download="handleDownload"
            @delete="handleDelete"
          />
        </div>
        <div v-else class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <p class="text-sm">{{ t('workspace.noFiles') }}</p>
        </div>
      </div>
    </div>
  </ResizablePanel>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { FolderOpen } from 'lucide-vue-next'
import ResizablePanel from './ResizablePanel.vue'
import WorkspaceFileTree from './WorkspaceFileTree.vue'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'downloadFile', 'deleteFile'])

const { t } = useLanguage()

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

const handleDownload = (item) => {
  emit('downloadFile', item)
}

const handleDelete = (item) => {
  emit('deleteFile', item)
}
</script>
