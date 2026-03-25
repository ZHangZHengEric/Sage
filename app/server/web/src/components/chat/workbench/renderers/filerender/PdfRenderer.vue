<template>
  <div class="h-full w-full bg-muted/20 flex flex-col">
    <iframe 
      v-if="fileUrl" 
      :src="fileUrl" 
      class="w-full h-full border-0"
      title="PDF Viewer"
    ></iframe>
    
    <div v-else class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground">
      <FileText class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">PDF 文件</p>
      <p class="text-xs text-muted-foreground/60 mb-4">无法加载预览</p>
      <Button variant="outline" size="sm" @click="downloadFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        下载 PDF
      </Button>
    </div>
  </div>
</template>

<script setup>
import { FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const props = defineProps({
  fileUrl: {
    type: String,
    default: ''
  }
})

const downloadFile = () => {
  if (props.fileUrl) {
    window.open(props.fileUrl, '_blank')
  }
}
</script>
