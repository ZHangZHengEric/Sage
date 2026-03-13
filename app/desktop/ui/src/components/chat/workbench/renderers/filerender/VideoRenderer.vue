<template>
  <div class="video-renderer h-full flex flex-col bg-black overflow-hidden">
    <!-- 视频播放器 - 使用 object-fit: contain 保持比例 -->
    <div class="flex-1 flex items-center justify-center relative overflow-hidden">
      <video
        v-if="videoUrl"
        ref="videoRef"
        :src="videoUrl"
        class="video-element"
        controls
        @error="handleError"
        @loadedmetadata="handleLoaded"
      ></video>

      <!-- 加载状态 -->
      <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-black/50">
        <Loader2 class="w-8 h-8 animate-spin text-white" />
      </div>

      <!-- 错误状态 -->
      <div v-if="error" class="absolute inset-0 flex flex-col items-center justify-center bg-black/80 text-white p-4">
        <AlertCircle class="w-12 h-12 mb-2 text-destructive" />
        <p class="text-sm">{{ error }}</p>
        <Button
          variant="outline"
          size="sm"
          @click="retryLoad"
          class="mt-4"
        >
          <RefreshCw class="w-4 h-4 mr-1" />
          重试
        </Button>
      </div>
    </div>

    <!-- 视频信息 -->
    <div class="flex-none px-4 py-2 bg-muted/10 border-t border-border/20 flex items-center justify-between">
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <Film class="w-4 h-4" />
        <span>{{ fileName }}</span>
      </div>
      <div v-if="duration" class="text-xs text-muted-foreground">
        {{ formatDuration(duration) }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { Button } from '@/components/ui/button'
import { Loader2, AlertCircle, RefreshCw, Film } from 'lucide-vue-next'
import { readFile } from '@tauri-apps/plugin-fs'

const props = defineProps({
  filePath: {
    type: String,
    required: true
  },
  fileName: {
    type: String,
    default: ''
  }
})

const videoRef = ref(null)
const loading = ref(true)
const error = ref('')
const duration = ref(0)
const videoUrl = ref('')

// 加载视频文件
const loadVideo = async () => {
  if (!props.filePath) return

  loading.value = true
  error.value = ''

  try {
    console.log('[VideoRenderer] Loading video from:', props.filePath)

    // 使用 Tauri 的 readFile 读取视频文件
    const fileData = await readFile(props.filePath)
    console.log('[VideoRenderer] File data size:', fileData.length)

    // 创建 Blob 和 URL
    const blob = new Blob([fileData], { type: 'video/mp4' })
    const url = URL.createObjectURL(blob)
    videoUrl.value = url

    console.log('[VideoRenderer] Created blob URL:', url)
  } catch (e) {
    console.error('[VideoRenderer] Failed to load video:', e)
    error.value = `视频加载失败: ${e.message || '无法读取文件'}`
    loading.value = false
  }
}

const handleError = (e) => {
  console.error('[VideoRenderer] Video load error:', e)
  error.value = `视频加载失败: ${e?.target?.error?.message || '不支持的格式'}`
  loading.value = false
}

const handleLoaded = () => {
  loading.value = false
  if (videoRef.value) {
    duration.value = videoRef.value.duration
  }
}

const retryLoad = () => {
  loadVideo()
}

// 格式化时长
const formatDuration = (seconds) => {
  if (!seconds || isNaN(seconds)) return ''
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

onMounted(() => {
  loadVideo()
})

onUnmounted(() => {
  // 清理视频资源
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
  // 释放 blob URL
  if (videoUrl.value && videoUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(videoUrl.value)
  }
})
</script>

<style scoped>
.video-renderer {
  min-height: 200px;
}

.video-element {
  /* 保持视频比例，自适应容器 */
  max-width: 100%;
  max-height: 100%;
  width: 100%;
  height: 100%;
  /* 使用 contain 保持比例，确保视频完全可见 */
  object-fit: contain;
  outline: none;
}

/* 自定义视频控制条样式 - 确保控制条可见 */
.video-element::-webkit-media-controls {
  background: linear-gradient(to top, rgba(0, 0, 0, 0.7), transparent) !important;
}

.video-element::-webkit-media-controls-panel {
  background: transparent !important;
}

/* 进度条样式 */
.video-element::-webkit-media-controls-timeline {
  background-color: rgba(255, 255, 255, 0.3);
  border-radius: 4px;
  height: 4px;
  margin: 0 10px;
}

.video-element::-webkit-media-controls-timeline-container {
  height: 20px;
}

/* 音量控制 */
.video-element::-webkit-media-controls-volume-slider {
  background-color: rgba(255, 255, 255, 0.3);
  border-radius: 4px;
  height: 4px;
}

/* 按钮样式 */
.video-element::-webkit-media-controls-play-button,
.video-element::-webkit-media-controls-mute-button,
.video-element::-webkit-media-controls-fullscreen-button {
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.5));
}

/* 时间显示 */
.video-element::-webkit-media-controls-current-time-display,
.video-element::-webkit-media-controls-time-remaining-display {
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  font-size: 13px;
}
</style>
