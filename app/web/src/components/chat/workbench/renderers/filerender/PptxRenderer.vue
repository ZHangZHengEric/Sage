<template>
  <div class="pptx-renderer h-full flex flex-col">
    <!-- 加载中 -->
    <div v-if="loading" class="flex items-center justify-center h-full text-muted-foreground">
      <div class="text-center">
        <Loader2 class="w-8 h-8 animate-spin mx-auto mb-2" />
        <p class="text-sm">正在加载 PPT...</p>
      </div>
    </div>
    <!-- 错误提示 -->
    <div v-else-if="error" class="flex flex-col items-center justify-center h-full text-muted-foreground">
      <FileText class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">PowerPoint 文件</p>
      <p class="text-xs text-destructive mb-4">{{ error }}</p>
      <Button variant="outline" size="sm" @click="downloadFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        下载文件
      </Button>
    </div>
    <!-- PPT 预览容器 -->
    <div v-show="!loading && !error" ref="containerRef" class="pptx-preview-container flex-1 overflow-auto">
      <!-- pptx-preview 将在这里渲染 -->
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Loader2, FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { init as initPptxPreview } from 'pptx-preview'

const props = defineProps({
  fileData: {
    type: [ArrayBuffer, Uint8Array],
    default: null
  },
  fileUrl: {
    type: String,
    default: ''
  }
})

const containerRef = ref(null)
const loading = ref(false)
const error = ref('')
let pptxApp = null

const loadPptx = async () => {
  if (!props.fileData || !containerRef.value) {
    // 如果还没有数据，保持 loading 或空状态
    return
  }

  loading.value = true
  error.value = ''

  try {
    await nextTick()

    // 确保容器可见且有尺寸
    containerRef.value.style.width = '100%'
    containerRef.value.style.height = '100%'
    containerRef.value.style.minHeight = '400px'

    // 获取容器实际尺寸
    const containerWidth = containerRef.value?.clientWidth || 800
    const containerHeight = containerRef.value?.clientHeight || 600

    // 清空容器
    containerRef.value.innerHTML = ''

    // 初始化 pptx-preview
    const pptxPreviewer = initPptxPreview(containerRef.value, {
      width: Math.floor(containerWidth),
      height: Math.floor(containerHeight),
      mode: 'list'
    })

    // 调用预览方法
    await pptxPreviewer.preview(props.fileData)

  } catch (err) {
    console.error('[PptxRenderer] Failed to render PPTX:', err)
    error.value = err.message || '无法渲染 PowerPoint 文件'
  } finally {
    loading.value = false
  }
}

const downloadFile = () => {
  if (props.fileUrl) {
    window.open(props.fileUrl, '_blank')
  }
}

watch(() => props.fileData, () => {
  loadPptx()
}, { immediate: true })

onUnmounted(() => {
  if (pptxApp) {
    // pptx-preview 似乎没有 destroy 方法，这里只是清理引用
    pptxApp = null
  }
})
</script>

<style scoped>
.pptx-renderer {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.pptx-preview-container {
  flex: 1;
  width: 100%;
  overflow: auto;
  display: flex;
  justify-content: center;
}

/* 让 pptx-preview 的容器占满高度 */
.pptx-preview-container :deep(> div) {
  width: 95% !important;
  height: 100% !important;
  max-width: 1200px;
}

/* 确保幻灯片列表占满高度 */
.pptx-preview-container :deep(.pptx-preview-list) {
  height: 100% !important;
}

/* 幻灯片样式 */
.pptx-preview-container :deep(.pptx-slide) {
  margin-bottom: 16px;
}

.pptx-preview-container :deep(.pptx-slide:last-child) {
  margin-bottom: 0;
}
</style>
