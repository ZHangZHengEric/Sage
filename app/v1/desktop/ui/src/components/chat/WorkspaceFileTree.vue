<template>
  <div class="file-tree-item select-none">
    <div 
      class="group flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-accent-foreground/80 transition-colors hover:bg-accent/35 hover:text-accent-foreground"
      :style="{ paddingLeft: `${level * 14 + 8}px` }"
      @click="toggleExpand"
    >
      <div class="flex items-center gap-2 min-w-0 overflow-hidden">
        <span class="text-muted-foreground shrink-0">
           <!-- Icons -->
           <ChevronRight v-if="item.is_directory && !isExpanded" class="w-3.5 h-3.5" />
           <ChevronDown v-else-if="item.is_directory && isExpanded" class="w-3.5 h-3.5" />
           <component :is="getFileIcon(item)" v-else class="w-3.5 h-3.5 text-muted-foreground/70" />
        </span>
        <span class="truncate text-[13px]">
          {{ item.name }}
        </span>
        <span v-if="!item.is_directory" class="ml-2 shrink-0 text-[10px] text-muted-foreground/50">
          {{ formatFileSize(item.size) }}
        </span>
      </div>

      <div class="flex items-center gap-1 ml-auto">
        <Button
          v-if="!item.is_directory"
          variant="ghost"
          size="icon"
          class="h-6 w-6 rounded-full opacity-0 transition-opacity group-hover:opacity-100"
          @click.stop="$emit('view', item)"
          title="查看文件"
        >
          <Eye class="w-3.5 h-3.5" />
        </Button>
        <!-- Quote Path Button -->
        <Button
          variant="ghost"
          size="icon"
          class="h-6 w-6 rounded-full opacity-0 transition-opacity group-hover:opacity-100"
          @click.stop="$emit('quote', item)"
          :title="item.is_directory ? '引用文件夹路径' : '引用文件路径'"
        >
          <Quote class="w-3.5 h-3.5" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          class="h-6 w-6 rounded-full opacity-0 transition-opacity group-hover:opacity-100"
          @click.stop="$emit('download', item)"
          :title="item.is_directory ? 'Download Folder' : 'Download File'"
        >
          <Download class="w-3.5 h-3.5" />
        </Button>

        <Button
          variant="ghost"
          size="icon"
          class="h-6 w-6 rounded-full opacity-0 transition-opacity group-hover:opacity-100 text-destructive hover:text-destructive hover:bg-destructive/10"
          @click.stop="$emit('delete', item)"
          :title="item.is_directory ? 'Delete Folder' : 'Delete File'"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>

    <div v-if="item.is_directory && isExpanded && item.children && item.children.length > 0">
      <WorkspaceFileTree
        v-for="(child, index) in item.children"
        :key="child?.path || `${level}-${index}`"
        :item="child"
        :level="level + 1"
        @download="$emit('download', $event)"
        @delete="$emit('delete', $event)"
        @quote="$emit('quote', $event)"
        @view="$emit('view', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { File, Folder, ChevronRight, ChevronDown, Download, Eye, FileJson, FileCode, FileText, Image, Trash2, Quote } from 'lucide-vue-next'
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

defineEmits(['download', 'delete', 'quote', 'view'])

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
