<template>
  <div class="h-full flex items-center justify-center bg-muted/20 overflow-hidden relative group">
    <div v-if="!imageUrl" class="text-muted-foreground flex flex-col items-center">
      <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">{{ t('workbench.image.loadError') }}</p>
      <p class="text-xs text-muted-foreground/60 mb-4">{{ fileName }}</p>
    </div>
    <img 
      v-else 
      :src="imageUrl" 
      :alt="fileName" 
      class="max-w-full max-h-full object-contain"
    />
    
    <div class="absolute bottom-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
      <Button variant="secondary" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        {{ t('workbench.image.open') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ImageIcon, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { convertFileSrc } from '@tauri-apps/api/core'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  fileName: {
    type: String,
    default: ''
  }
})

const imageUrl = computed(() => {
  if (!props.filePath) return ''
  // 如果已经是 asset:// 或 http:// URL，直接返回
  if (props.filePath.startsWith('asset://') || props.filePath.startsWith('http://') || props.filePath.startsWith('https://')) {
    return props.filePath
  }
  let cleanPath = props.filePath
  // 如果已经是 file:// URL，去掉协议头
  if (props.filePath.startsWith('file://')) {
    cleanPath = props.filePath.replace(/^file:\/\//i, '')
  }
  // 去掉开头的 /，因为 convertFileSrc 会将其编码为 %2F
  cleanPath = cleanPath.replace(/^\//, '')
  // 使用 Tauri 的 convertFileSrc 转换本地路径
  return convertFileSrc(cleanPath)
})

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}
</script>
