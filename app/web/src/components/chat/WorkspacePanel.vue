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
      <div v-if="workspacePath" class="text-xs text-muted-foreground bg-muted p-2 rounded-md break-all">
        <strong class="font-medium text-foreground">{{ t('workspace.path') }}</strong> {{ workspacePath }}
      </div>
      
      <div class="space-y-2">
        <div v-if="hasValidFiles" class="grid gap-2">
          <div 
            v-for="(file, index) in workspaceFiles" 
            :key="file.path || index"
            class="flex items-center justify-between p-2 rounded-lg border border-border bg-card hover:bg-accent hover:text-accent-foreground transition-colors group"
          >
            <div class="flex items-center gap-3 min-w-0">
              <span class="text-lg shrink-0">
                {{ getFileIcon(file.name || file.path) }}
              </span>
              <div class="flex flex-col min-w-0">
                <span class="text-sm font-medium truncate">
                  {{ file.name || file.path }}
                </span>
                <span v-if="file.size" class="text-[10px] text-muted-foreground">
                  {{ formatFileSize(file.size) }}
                </span>
              </div>
            </div>
            
            <Button 
              variant="ghost" 
              size="icon" 
              class="h-8 w-8 opacity-0 group-hover:opacity-100 transition-opacity"
              @click="handleDownload(file.name || file.path)"
              :title="t('workspace.download')"
            >
              <Download class="w-4 h-4" />
            </Button>
          </div>
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
import { X, Download } from 'lucide-vue-next'

const props = defineProps({
  workspaceFiles: {
    type: Array,
    default: () => []
  },
  workspacePath: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'downloadFile'])

const { t } = useLanguage()

const hasValidFiles = computed(() => {
  return props.workspaceFiles && props.workspaceFiles.length > 0
})

const getFileIcon = (filename) => {
  if (!filename) return '📄'
  
  const ext = filename.split('.').pop()?.toLowerCase()
  
  switch (ext) {
    case 'js':
    case 'jsx':
    case 'ts':
    case 'tsx':
      return '📜'
    case 'vue':
      return '🔧'
    case 'py':
      return '🐍'
    case 'json':
      return '📋'
    case 'md':
      return '📝'
    case 'txt':
      return '📄'
    case 'css':
    case 'scss':
    case 'less':
      return '🎨'
    case 'html':
      return '🌐'
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'gif':
    case 'svg':
      return '🖼️'
    case 'pdf':
      return '📕'
    case 'zip':
    case 'rar':
    case 'tar':
    case 'gz':
      return '📦'
    default:
      return '📄'
  }
}

const formatFileSize = (bytes) => {
  if (!bytes) return ''
  
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i]
}

const handleDownload = (filename) => {
  emit('downloadFile', filename)
}
</script>

<style scoped>
/* Removed custom styles in favor of Tailwind classes */
</style>