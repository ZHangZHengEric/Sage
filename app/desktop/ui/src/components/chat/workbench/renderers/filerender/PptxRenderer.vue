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
      <Button variant="outline" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        打开文件
      </Button>
    </div>
    <!-- PPT 预览容器 -->
    <div v-show="!loading && !error" class="flex flex-col flex-1 overflow-hidden">
      <!-- 提示信息 -->
      <div class="bg-amber-50 dark:bg-amber-950 border-b border-amber-200 dark:border-amber-800 px-4 py-2 flex items-center justify-between shrink-0">
        <p class="text-xs text-amber-700 dark:text-amber-300">
          <span class="font-medium">提示：</span>预览效果可能与实际文件有差异，建议用 PowerPoint 或 WPS 打开查看
        </p>
        <Button variant="ghost" size="sm" class="h-6 text-xs" @click="openFile">
          <ExternalLink class="w-3 h-3 mr-1" />
          打开文件
        </Button>
      </div>
      <div ref="containerRef" class="pptx-preview-container flex-1 overflow-auto">
        <!-- pptx-preview 将在这里渲染 -->
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { Loader2, FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { init as initPptxPreview } from 'pptx-preview'
import { readFile } from '@tauri-apps/plugin-fs'

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  }
})

const containerRef = ref(null)
const loading = ref(false)
const error = ref('')
let pptxApp = null

const cleanupPreview = () => {
  if (pptxApp && typeof pptxApp.destroy === 'function') {
    pptxApp.destroy()
  }
  pptxApp = null
  if (containerRef.value) {
    containerRef.value.innerHTML = ''
  }
}

const loadPptx = async () => {
  if (!props.filePath || !containerRef.value) {
    error.value = '文件路径无效'
    return
  }

  loading.value = true
  error.value = ''

  try {
    await nextTick()

    // 读取文件为二进制
    const fileData = await readFile(props.filePath)
    const arrayBuffer = new Uint8Array(fileData).buffer

    // 确保容器可见且有尺寸
    containerRef.value.style.width = '100%'
    containerRef.value.style.height = '100%'
    containerRef.value.style.minHeight = '400px'

    // 获取容器实际尺寸
    const containerWidth = containerRef.value?.clientWidth || 800
    const containerHeight = containerRef.value?.clientHeight || 600

    console.log('[PptxRenderer] Container dimensions:', { containerWidth, containerHeight })

    // 清空容器
    cleanupPreview()

    // 初始化 pptx-preview
    console.log('[PptxRenderer] Initializing pptx-preview...')
    pptxApp = initPptxPreview(containerRef.value, {
      width: Math.floor(containerWidth),
      height: Math.floor(containerHeight),
      mode: 'list' // 使用 list 模式，支持上下滚动
    })

    console.log('[PptxRenderer] Previewer initialized:', pptxApp)

    // 调用预览方法
    console.log('[PptxRenderer] Calling preview method...')
    await pptxApp.preview(arrayBuffer)

    console.log('[PptxRenderer] PPTX rendered successfully')
  } catch (err) {
    console.error('[PptxRenderer] Failed to render PPTX:', err)
    error.value = err.message || '无法渲染 PowerPoint 文件'
  } finally {
    loading.value = false
  }
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

onMounted(() => {
  // 延迟加载，确保容器已渲染
  setTimeout(() => {
    loadPptx()
  }, 100)
})

onUnmounted(() => {
  cleanupPreview()
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
