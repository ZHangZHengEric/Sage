<template>
  <div class="w-[35%] flex flex-col border-l border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
    <div class="flex items-center justify-between p-4 border-b border-border">
      <h3 class="text-base font-semibold">{{ t('workspace.title') }}</h3>
      <Button 
        variant="ghost" 
        size="icon" 
        class="h-8 w-8" 
        @click="$emit('close')"
      >
        <X class="w-4 h-4" />
      </Button>
    </div>
    
    <div class="flex-1 overflow-y-auto p-4 space-y-4">

      <div class="space-y-1">
        <div v-if="hasValidFiles" class="flex flex-col gap-1">
          <WorkspaceFileTree 
            v-for="node in fileTree" 
            :key="node.path" 
            :item="node" 
            @download="handleDownload"
          />
        </div>
        <div v-else class="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <p class="text-sm">{{ t('workspace.noFiles') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '../../utils/i18n.js'
import { Button } from '@/components/ui/button'
import { X } from 'lucide-vue-next'
import WorkspaceFileTree from './WorkspaceFileTree.vue'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['close', 'downloadFile'])

const { t } = useLanguage()

const hasValidFiles = computed(() => {
  return props.workspaceFiles && props.workspaceFiles.length > 0
})

const fileTree = computed(() => {
  if (!props.workspaceFiles || props.workspaceFiles.length === 0) return []
  
  const root = []
  const map = {}
  
  // Initialize map with all items
  // Deep copy to avoid mutating props and to handle children array
  props.workspaceFiles.forEach(file => {
    map[file.path] = { ...file, children: [] }
  })
  
  // Build tree
  props.workspaceFiles.forEach(file => {
    const node = map[file.path]
    const parts = file.path.split('/')
    if (parts.length > 1) {
      const parentPath = parts.slice(0, -1).join('/')
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
  emit('downloadFile', item.path)
}
</script>

