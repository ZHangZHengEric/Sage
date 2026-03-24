<template>
  <div class="h-full flex items-center justify-center bg-muted/20 overflow-hidden relative group">
    <!-- 加载中 -->
    <div v-if="loading" class="text-muted-foreground flex flex-col items-center">
      <Loader2 class="w-8 h-8 animate-spin text-primary mb-2" />
      <p class="text-sm">{{ t('workbench.image.loading') }}</p>
    </div>
    
    <!-- 错误状态 -->
    <div v-else-if="error" class="text-muted-foreground flex flex-col items-center">
      <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">{{ t('workbench.image.loadError') }}</p>
      <p class="text-xs text-muted-foreground/60 mb-4">{{ fileName }}</p>
    </div>
    
    <!-- SVG 内容直接渲染 -->
    <div 
      v-else-if="isSvg" 
      class="max-w-full max-h-full overflow-auto flex items-center justify-center"
    >
      <div 
        v-if="svgContent" 
        class="svg-container"
        v-html="svgContent"
      />
      <div v-else-if="error" class="text-muted-foreground flex flex-col items-center">
        <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
        <p class="text-sm mb-1">{{ t('workbench.image.loadError') }}</p>
        <p class="text-xs text-muted-foreground/60 mb-4">{{ fileName }}</p>
      </div>
    </div>
    
    <!-- 普通图片 -->
    <img 
      v-else-if="imageUrl" 
      :src="imageUrl" 
      :alt="fileName" 
      class="max-w-full max-h-full object-contain"
      @load="loading = false"
      @error="handleImageError"
    />
    
    <!-- 无法加载 -->
    <div v-else class="text-muted-foreground flex flex-col items-center">
      <ImageIcon class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">{{ t('workbench.image.loadError') }}</p>
      <p class="text-xs text-muted-foreground/60 mb-4">{{ fileName }}</p>
    </div>
    
    <div class="absolute bottom-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
      <Button variant="secondary" size="sm" @click="openFile">
        <ExternalLink class="w-4 h-4 mr-1" />
        {{ t('workbench.image.open') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { ImageIcon, ExternalLink, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { convertFileSrc } from '@tauri-apps/api/core'
import { readTextFile } from '@tauri-apps/plugin-fs'
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

const loading = ref(true)
const error = ref(false)
const svgContent = ref('')

// 判断是否为 SVG 文件
const isSvg = computed(() => {
  // 从 filePath 提取文件名（移除路径和查询参数）
  const path = props.filePath || ''
  const fileNameFromPath = path.split('/').pop()?.split('?')[0] || ''
  const name = props.fileName || fileNameFromPath
  const result = name.toLowerCase().endsWith('.svg')
  console.log('[ImageRenderer] isSvg check:', { 
    fileName: props.fileName, 
    filePath: props.filePath, 
    fileNameFromPath,
    name, 
    result,
    lastChars: name.slice(-10)
  })
  return result
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

// 加载 SVG 内容
const loadSvgContent = async () => {
  if (!isSvg.value) {
    loading.value = false
    return
  }
  
  try {
    loading.value = true
    error.value = false
    
    // 获取文件路径（去掉 file:// 前缀）
    let filePath = props.filePath
    if (filePath.startsWith('file://')) {
      filePath = filePath.replace(/^file:\/\//i, '')
    }
    
    // 读取 SVG 文件内容
    const content = await readTextFile(filePath)
    
    // 清理 SVG 内容，确保可以安全渲染
    // 移除可能存在的 XML 声明和 DOCTYPE
    let cleanedContent = content
      .replace(/<\?xml[^?]*\?>/gi, '')
      .replace(/<!DOCTYPE[^>]*>/gi, '')
      .trim()
    
    svgContent.value = cleanedContent
    loading.value = false
  } catch (err) {
    console.error('加载 SVG 失败:', err)
    error.value = true
    loading.value = false
  }
}

const handleImageError = () => {
  loading.value = false
  error.value = true
}

const openFile = () => {
  if (props.filePath) {
    window.__TAURI__.shell.open(props.filePath)
  }
}

onMounted(() => {
  console.log('[ImageRenderer] onMounted, fileName:', props.fileName, 'filePath:', props.filePath, 'isSvg:', isSvg.value)
  if (isSvg.value) {
    loadSvgContent()
  } else {
    loading.value = false
  }
})
</script>
