<template>
  <div class="h-full flex items-center justify-center bg-muted/20 overflow-hidden relative group">
    <!-- 错误 -->
    <div v-if="error" class="text-muted-foreground flex flex-col items-center">
      <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">{{ t('workbench.image.loadError') }}</p>
      <p class="text-xs text-muted-foreground/60 mb-4">{{ fileName }}</p>
    </div>

    <!-- SVG -->
    <div
      v-else-if="isSvg"
      class="relative max-w-full max-h-full w-full h-full overflow-auto flex items-center justify-center"
    >
      <div
        v-if="svgBusy"
        class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-muted/30 text-muted-foreground"
      >
        <Loader2 class="w-8 h-8 animate-spin text-primary mb-2" />
        <p class="text-sm">{{ t('workbench.image.loading') }}</p>
      </div>
      <div
        v-if="svgContent"
        class="svg-container"
        v-html="svgContent"
      />
    </div>

    <!-- 栅格图：img 与加载叠层分离，避免 loading 阻挡挂载导致永远不触发 load -->
    <div
      v-else
      class="relative flex-1 min-h-0 w-full h-full flex items-center justify-center"
    >
      <img
        v-if="rasterSrc"
        :src="rasterSrc"
        :alt="fileName"
        class="max-w-full max-h-full object-contain relative z-0"
        @error="handleImageError"
      />
      <div
        v-if="rasterBusy"
        class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-muted/40 text-muted-foreground"
      >
        <Loader2 class="w-8 h-8 animate-spin text-primary mb-2" />
        <p class="text-sm">{{ t('workbench.image.loading') }}</p>
      </div>
      <div
        v-if="!rasterBusy && !rasterSrc"
        class="text-muted-foreground flex flex-col items-center relative z-0"
      >
        <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">{{ t('workbench.image.loadError') }}</p>
        <p class="text-xs text-muted-foreground/60 mb-4">{{ fileName }}</p>
      </div>
    </div>

    <div class="absolute bottom-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity z-20">
      <Button variant="secondary" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        {{ t('workbench.image.open') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { ImageIcon, ExternalLink, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { convertFileSrc } from '@tauri-apps/api/core'
import { readTextFile } from '@tauri-apps/plugin-fs'
import { useLanguage } from '@/utils/i18n'
import {
  parseAgentWorkspaceAbsolutePath,
  createWorkspaceBlobUrlViaBackend,
  readWorkspaceTextViaBackend,
} from '@/utils/agentWorkspaceBackend.js'

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

const error = ref(false)
const svgBusy = ref(false)
const rasterBusy = ref(false)
const svgContent = ref('')
const rasterSrc = ref('')
/** @type {string[]} */
const blobUrlsToRevoke = []

const revokeRasterBlobs = () => {
  blobUrlsToRevoke.forEach((u) => {
    try {
      URL.revokeObjectURL(u)
    } catch (_) { /* noop */ }
  })
  blobUrlsToRevoke.length = 0
}

/** 优先用路径上的扩展名（链接文案常常没有后缀，误判 SVG 会走后端读文本卡死） */
const isSvg = computed(() => {
  const raw = props.filePath || ''
  const fromPath = raw.split(/[/\\]/).pop()?.split('?')[0] || ''
  if (fromPath.toLowerCase().endsWith('.svg')) return true
  if (fromPath.includes('.')) return false
  const title = (props.fileName || '').trim()
  return title.toLowerCase().endsWith('.svg')
})

const loadSvgContent = async () => {
  if (!isSvg.value) return

  svgBusy.value = true
  error.value = false
  svgContent.value = ''

  try {
    let diskPath = props.filePath.replace(/^file:\/\//i, '')
    const parsed = parseAgentWorkspaceAbsolutePath(diskPath)
    const content = parsed
      ? await readWorkspaceTextViaBackend(parsed.agentId, parsed.relativePath)
      : await readTextFile(diskPath)

    svgContent.value = content
      .replace(/<\?xml[^?]*\?>/gi, '')
      .replace(/<!DOCTYPE[^>]*>/gi, '')
      .trim()
  } catch (err) {
    console.error('加载 SVG 失败:', err)
    error.value = true
  } finally {
    svgBusy.value = false
  }
}

const loadRaster = async () => {
  revokeRasterBlobs()
  rasterSrc.value = ''
  rasterBusy.value = false
  error.value = false

  const fp = props.filePath
  if (!fp) return

  if (/^(asset:|https?:|data:|blob:)/i.test(fp)) {
    rasterSrc.value = fp
    return
  }

  const cleanPath = fp.replace(/^file:\/\//i, '')
  const parsed = parseAgentWorkspaceAbsolutePath(cleanPath)
  if (parsed) {
    rasterBusy.value = true
    try {
      const url = await createWorkspaceBlobUrlViaBackend(parsed.agentId, parsed.relativePath)
      blobUrlsToRevoke.push(url)
      rasterSrc.value = url
    } catch (err) {
      console.error('工作台图片经后端加载失败:', err)
      error.value = true
    } finally {
      rasterBusy.value = false
    }
    return
  }

  rasterSrc.value = convertFileSrc(cleanPath)
}

const handleImageError = () => {
  error.value = true
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

const loadPreview = async () => {
  error.value = false
  svgContent.value = ''
  svgBusy.value = false
  rasterBusy.value = false
  revokeRasterBlobs()
  rasterSrc.value = ''

  if (!props.filePath) return

  if (isSvg.value) {
    await loadSvgContent()
  } else {
    await loadRaster()
  }
}

onMounted(() => {
  loadPreview()
})

watch(
  () => props.filePath,
  (next, prev) => {
    if (next === prev) return
    loadPreview()
  }
)

onUnmounted(() => {
  revokeRasterBlobs()
})
</script>
