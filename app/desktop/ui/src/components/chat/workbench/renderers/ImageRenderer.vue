<template>
  <div class="image-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-xl">{{ isSvg ? '🎨' : '🖼️' }}</span>
        <span class="text-sm font-medium truncate">{{ displayAlt }}</span>
        <Badge variant="secondary" class="text-xs">{{ isSvg ? 'SVG' : '图片' }}</Badge>
      </div>
    </div>

    <!-- SVG 内容 -->
    <div v-if="isSvg" class="flex-1 overflow-auto p-4 flex items-center justify-center bg-muted/10">
      <div 
        v-if="svgContent" 
        class="svg-container max-w-full max-h-full"
        v-html="svgContent"
      />
      <div v-else class="text-muted-foreground flex flex-col items-center">
        <span class="text-5xl mb-2">🎨</span>
        <p class="text-sm">加载 SVG 中...</p>
      </div>
    </div>

    <!-- 普通图片内容 -->
    <div v-else class="flex-1 overflow-auto p-4 flex items-center justify-center bg-muted/10">
      <img
        :src="src"
        :alt="displayAlt"
        class="max-w-full max-h-full h-auto rounded-lg shadow-md cursor-pointer hover:shadow-lg transition-shadow"
        @click="isPreviewOpen = true"
      />
    </div>

    <!-- 图片预览对话框 -->
    <Dialog v-if="!isSvg" v-model:open="isPreviewOpen">
      <DialogContent class="max-w-[90vw] max-h-[90vh] p-0 bg-background/95">
        <img :src="src" :alt="displayAlt" class="w-full h-full object-contain" />
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { readFile, readTextFile } from '@tauri-apps/plugin-fs'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

const isPreviewOpen = ref(false)
const imageSrc = ref('')
const svgContent = ref('')

// 检查是否为本地绝对路径
const isLocalAbsolutePath = (path) => {
  if (!path) return false
  const unixPattern = /^\/((Users|home|Volumes|private|tmp|var|opt|Applications|System|Library)\/.+|\.sage\/.+)/
  const windowsPattern = /^[a-zA-Z]:[\\/]/
  const fileProtocolPattern = /^file:\/\//i
  return unixPattern.test(path) || windowsPattern.test(path) || fileProtocolPattern.test(path)
}

// 读取本地图片文件并转换为 Data URL
const loadLocalImage = async (localPath) => {
  try {
    // 去掉 file:// 协议头
    let cleanPath = localPath
    if (/^file:\/\//i.test(localPath)) {
      cleanPath = localPath.replace(/^file:\/\//i, '')
    }
    console.log('[ImageRenderer] Loading image from:', cleanPath)
    
    // 读取文件内容为 Uint8Array
    const fileData = await readFile(cleanPath)
    console.log('[ImageRenderer] File loaded, size:', fileData.length)
    
    // 转换为 Blob
    const blob = new Blob([fileData])
    
    // 创建 Object URL
    const objectUrl = URL.createObjectURL(blob)
    console.log('[ImageRenderer] Created object URL:', objectUrl)
    
    return objectUrl
  } catch (error) {
    console.error('[ImageRenderer] Failed to load image:', error)
    return ''
  }
}

// 从 item 中提取图片信息
const rawSrc = computed(() => {
  return props.item.data?.src || props.item.data?.imageUrl || props.item.data?.filePath || ''
})

// 判断是否为 SVG 文件
const isSvg = computed(() => {
  const src = rawSrc.value
  if (!src) return false
  // 从路径提取文件名
  const fileName = src.split('/').pop()?.split('?')[0] || ''
  return fileName.toLowerCase().endsWith('.svg')
})

// 加载 SVG 内容
const loadSvgContent = async (localPath) => {
  try {
    // 去掉 file:// 协议头
    let cleanPath = localPath
    if (/^file:\/\//i.test(localPath)) {
      cleanPath = localPath.replace(/^file:\/\//i, '')
    }
    console.log('[ImageRenderer] Loading SVG from:', cleanPath)

    // 读取 SVG 文件内容
    const content = await readTextFile(cleanPath)
    console.log('[ImageRenderer] SVG loaded, size:', content.length)

    // 清理 SVG 内容
    const cleanedSvg = content
      .replace(/<\?xml[^?]*\?>/gi, '')
      .replace(/<!DOCTYPE[^>]*>/gi, '')
      .trim()

    return cleanedSvg
  } catch (error) {
    console.error('[ImageRenderer] Failed to load SVG:', error)
    return ''
  }
}

// 加载图片的函数
const loadImage = async () => {
  console.log('[ImageRenderer] item:', props.item)
  console.log('[ImageRenderer] item.data:', props.item?.data)
  console.log('[ImageRenderer] rawSrc:', rawSrc.value)
  console.log('[ImageRenderer] isSvg:', isSvg.value)

  if (isSvg.value) {
    // SVG 文件：直接读取文本内容
    if (isLocalAbsolutePath(rawSrc.value)) {
      svgContent.value = await loadSvgContent(rawSrc.value)
    } else {
      // 在线 SVG，直接作为图片加载
      imageSrc.value = rawSrc.value
    }
  } else if (isLocalAbsolutePath(rawSrc.value)) {
    // 普通本地图片
    imageSrc.value = await loadLocalImage(rawSrc.value)
  } else {
    // 在线图片
    imageSrc.value = rawSrc.value
  }
}

// 组件挂载时加载图片
onMounted(loadImage)

// 监听 item 变化，切换图片时重新加载
watch(() => props.item?.id, async (newId, oldId) => {
  if (newId !== oldId) {
    console.log('[ImageRenderer] Item changed, reloading image:', newId)
    // 释放之前的 Object URL
    if (imageSrc.value && imageSrc.value.startsWith('blob:')) {
      URL.revokeObjectURL(imageSrc.value)
    }
    await loadImage()
  }
}, { immediate: false })

const src = computed(() => imageSrc.value)

const alt = computed(() => {
  return props.item.data?.alt || props.item.data?.name || ''
})

const displayAlt = computed(() => {
  return alt.value || '图片'
})

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': 'AI',
    'user': '用户',
    'system': '系统',
    'tool': '工具'
  }
  return roleMap[props.item?.role] || 'AI'
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}
</script>

<style scoped>
.svg-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.svg-container svg {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
}
</style>
