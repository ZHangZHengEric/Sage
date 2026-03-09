<template>
  <div class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground bg-muted/20">
    <FileText class="w-16 h-16 mb-3 opacity-50" />
    <p class="text-sm mb-1">PDF 文件</p>
    <p class="text-xs text-muted-foreground/60 mb-4">由于浏览器安全限制，无法直接预览本地 PDF</p>
    <Button variant="outline" size="sm" @click="openFile">
      <ExternalLink class="w-4 h-4 mr-1" />
      打开 PDF
    </Button>
  </div>
</template>

<script setup>
import { FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  }
})

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}
</script>
