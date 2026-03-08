<template>
  <div class="h-full flex flex-col">
    <!-- HTML 工具栏 -->
    <div class="flex items-center justify-between px-3 py-2 bg-muted/30 border-b border-border flex-none">
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <Globe class="w-3 h-3" />
        <span>HTML 预览</span>
      </div>
      <div class="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          class="h-7 px-2 text-xs"
          @click="refreshPreview"
        >
          <RefreshCw class="w-3 h-3 mr-1" />
          刷新
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="h-7 px-2 text-xs"
          @click="openFile"
        >
          <ExternalLink class="w-3 h-3 mr-1" />
          外部打开
        </Button>
      </div>
    </div>
    <!-- HTML iframe 渲染 -->
    <div class="flex-1 relative bg-white">
      <iframe
        v-if="dataUrl"
        :src="dataUrl"
        class="w-full h-full border-0"
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        title="HTML Preview"
      ></iframe>
      <div v-else class="h-full flex items-center justify-center text-muted-foreground">
        <div class="text-center">
          <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
          <p class="text-sm">加载中...</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { Globe, RefreshCw, ExternalLink, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  },
  content: {
    type: String,
    default: ''
  }
})

const dataUrl = ref('')

const createDataUrl = () => {
  if (props.content) {
    const blob = new Blob([props.content], { type: 'text/html' })
    dataUrl.value = URL.createObjectURL(blob)
  }
}

const refreshPreview = () => {
  if (dataUrl.value) {
    URL.revokeObjectURL(dataUrl.value)
  }
  createDataUrl()
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

onMounted(() => {
  createDataUrl()
})

watch(() => props.content, () => {
  refreshPreview()
})
</script>
