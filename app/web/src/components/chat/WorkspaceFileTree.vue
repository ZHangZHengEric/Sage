<template>
  <div class="file-tree-item select-none">
    <div 
      class="flex items-center justify-between py-1 px-2 rounded-md hover:bg-accent/50 text-accent-foreground/80 hover:text-accent-foreground transition-colors group cursor-pointer"
      :style="{ paddingLeft: `${level * 16 + 8}px` }"
      @click="toggleExpand"
    >
      <div class="flex items-center gap-2 min-w-0 overflow-hidden">
        <span class="text-muted-foreground shrink-0">
           <!-- Icons -->
           <ChevronRight v-if="item.is_directory && !isExpanded" class="w-4 h-4" />
           <ChevronDown v-else-if="item.is_directory && isExpanded" class="w-4 h-4" />
           <component :is="getFileIcon(item)" v-else class="w-4 h-4 text-muted-foreground/70" />
        </span>
        <span class="text-sm truncate">
          {{ item.name }}
        </span>
        <span v-if="!item.is_directory" class="text-[10px] text-muted-foreground/50 ml-2 shrink-0">
          {{ formatFileSize(item.size) }}
        </span>
      </div>

      <Button 
        variant="ghost" 
        size="icon" 
        class="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
        @click.stop="$emit('download', item)"
        :title="item.is_directory ? 'Download Folder' : 'Download File'"
      >
        <Download class="w-3.5 h-3.5" />
      </Button>
    </div>

    <div v-if="item.is_directory && isExpanded">
      <WorkspaceFileTree 
        v-for="child in item.children" 
        :key="child.path" 
        :item="child" 
        :level="level + 1"
        @download="$emit('download', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { File, Folder, ChevronRight, ChevronDown, Download, FileJson, FileCode, FileText, Image } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

defineOptions({
  name: 'WorkspaceFileTree'
})

const props = defineProps({
  item: {
    type: Object,
    required: true
  },
  level: {
    type: Number,
    default: 0
  }
})

defineEmits(['download'])

const isExpanded = ref(false)

const toggleExpand = () => {
  if (props.item.is_directory) {
    isExpanded.value = !isExpanded.value
  }
}

const getFileIcon = (file) => {
  if (file.is_directory) return Folder
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (['json', 'yaml', 'yml'].includes(ext)) return FileJson
  if (['js', 'ts', 'py', 'java', 'go', 'rs', 'c', 'cpp', 'h', 'css', 'html', 'vue', 'jsx', 'tsx'].includes(ext)) return FileCode
  if (['md', 'txt', 'log'].includes(ext)) return FileText
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return Image
  return File
}

const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}
</script>
