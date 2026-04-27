<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- 参数行 -->
    <div class="px-4 py-2.5 border-b border-border flex items-center gap-2 flex-none flex-wrap bg-muted/20">
      <component :is="isUrl ? Globe : FileImage" class="w-4 h-4 text-muted-foreground flex-shrink-0" />
      <code class="font-mono text-xs text-muted-foreground break-all flex-1 min-w-0 truncate" :title="imagePath">{{ imagePath }}</code>
      <Badge v-if="customPrompt" variant="outline" class="text-xs max-w-[180px] truncate flex-shrink-0" :title="customPrompt">
        {{ customPrompt }}
      </Badge>
    </div>

    <!-- 加载中 -->
    <div v-if="isLoading" class="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
      <Loader2 class="w-6 h-6 animate-spin text-primary" />
      <span class="text-sm">{{ t('workbench.tool.analyzing') || '正在分析图片...' }}</span>
    </div>

    <!-- 错误 -->
    <div v-else-if="isError" class="flex-1 overflow-auto p-4">
      <div class="rounded-lg border border-destructive/30 bg-destructive/10 p-4 flex items-start gap-3">
        <AlertCircle class="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
        <p class="text-sm text-destructive whitespace-pre-wrap">{{ errorMessage }}</p>
      </div>
    </div>

    <!-- 成功：图片 + 分析结果 -->
    <div v-else-if="hasResult" class="flex-1 flex flex-col md:flex-row overflow-hidden">
      <!-- 左：图片预览 -->
      <div class="md:w-56 lg:w-72 flex-shrink-0 border-b md:border-b-0 md:border-r border-border/50 bg-muted/10 flex flex-col overflow-hidden">
        <!-- 图片区域 -->
        <div class="flex-1 flex items-center justify-center p-3 overflow-hidden">
          <!-- 加载中 -->
          <div v-if="imgLoading" class="flex flex-col items-center gap-2 text-muted-foreground text-xs">
            <Loader2 class="w-5 h-5 animate-spin" />
            加载图片...
          </div>
          <!-- 错误 -->
          <div v-else-if="imgFailed" class="flex flex-col items-center gap-2 text-muted-foreground text-xs text-center px-2">
            <ImageOff class="w-8 h-8 opacity-40" />
            <span>无法预览图片</span>
            <span class="text-[10px] break-all opacity-60">{{ imagePath }}</span>
          </div>
          <!-- 图片 -->
          <img
            v-else-if="displaySrc"
            :src="displaySrc"
            class="max-w-full max-h-full object-contain rounded-lg shadow cursor-pointer hover:shadow-md transition-shadow"
            @click="previewOpen = true"
            @error="imgFailed = true"
          />
        </div>
        <!-- 文件名 -->
        <div class="px-3 pb-2 text-[10px] text-muted-foreground truncate text-center" :title="imagePath">
          {{ fileName }}
        </div>
      </div>

      <!-- 右：分析结果 -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <div class="px-4 pt-3 pb-2 flex items-center gap-2 text-xs text-muted-foreground font-medium flex-shrink-0">
          <ScanText class="w-3.5 h-3.5" />
          {{ t('workbench.tool.analysisResult') || '分析结果' }}
        </div>
        <div class="flex-1 overflow-auto px-4 pb-4">
          <MarkdownRenderer :content="description" />
        </div>
      </div>
    </div>

    <!-- 图片放大预览 -->
    <Dialog v-if="displaySrc" v-model:open="previewOpen">
      <DialogContent class="max-w-[90vw] max-h-[90vh] p-2 bg-background/95 flex items-center justify-center">
        <img :src="displaySrc" class="max-w-full max-h-[85vh] object-contain rounded" />
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch, onUnmounted } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Globe, FileImage, Loader2, AlertCircle, ScanText, ImageOff } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'

const { t } = useLanguage()

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

// ── 参数 ──────────────────────────────────────────
const imagePath = computed(() => props.toolArgs.image_path || '')
const customPrompt = computed(() => props.toolArgs.prompt || '')
const isUrl = computed(() => /^https?:\/\//i.test(imagePath.value))
const fileName = computed(() => imagePath.value.split('/').pop().split('\\').pop() || imagePath.value)

// ── 结果解析 ──────────────────────────────────────
const isLoading = computed(() => !props.toolResult)

// toolResult 结构: { content: {...} | string, is_error: bool }
const parsedContent = computed(() => {
  const c = props.toolResult?.content
  if (c == null) return null
  if (typeof c === 'string') {
    try { return JSON.parse(c) } catch { return null }
  }
  return c
})

const isError = computed(() => {
  if (props.toolResult?.is_error) return true
  return parsedContent.value?.status === 'error'
})
const errorMessage = computed(() => {
  if (props.toolResult?.is_error) {
    const c = props.toolResult.content
    return typeof c === 'string' ? c : (c?.message || JSON.stringify(c))
  }
  return parsedContent.value?.message || ''
})
const description = computed(() => parsedContent.value?.data?.description || '')
const hasResult = computed(() => !!description.value)

// ── 图片显示 ──────────────────────────────────────
const imgLoading = ref(false)
const imgFailed = ref(false)
const localObjectUrl = ref('')
const previewOpen = ref(false)

// URL 图片直接使用；server-web 无法读取用户本机路径
const displaySrc = computed(() => {
  if (isUrl.value) return imagePath.value
  return localObjectUrl.value
})

const loadLocalImage = async (path) => {
  if (!path || isUrl.value) return
  if (localObjectUrl.value) {
    URL.revokeObjectURL(localObjectUrl.value)
    localObjectUrl.value = ''
  }
  imgLoading.value = false
  imgFailed.value = true
}

// 结果到达后才加载图片（避免工具还在运行时浪费请求）
watch(
  () => props.toolResult,
  (newVal) => {
    if (newVal && !isUrl.value && imagePath.value) {
      loadLocalImage(imagePath.value)
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  if (localObjectUrl.value) URL.revokeObjectURL(localObjectUrl.value)
})
</script>
