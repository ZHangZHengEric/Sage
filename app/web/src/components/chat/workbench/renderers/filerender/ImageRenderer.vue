<template>
  <div class="h-full flex items-center justify-center bg-muted/20 overflow-hidden relative group">
    <div v-if="!fileUrl" class="text-muted-foreground flex flex-col items-center">
      <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm">{{ t('workbench.image.loadError') }}</p>
    </div>
    <img 
      v-else 
      :src="fileUrl" 
      :alt="fileName" 
      class="max-w-full max-h-full object-contain"
    />
    
    <div class="absolute bottom-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
      <Button variant="secondary" size="sm" @click="downloadFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        {{ t('workbench.image.download') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { ImageIcon, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()

const props = defineProps({
  fileUrl: {
    type: String,
    default: ''
  },
  fileName: {
    type: String,
    default: ''
  }
})

const downloadFile = () => {
  if (props.fileUrl) {
    // 如果是 Blob URL，需要创建 <a> 标签下载
    const a = document.createElement('a')
    a.href = props.fileUrl
    a.download = props.fileName || 'image'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }
}
</script>
