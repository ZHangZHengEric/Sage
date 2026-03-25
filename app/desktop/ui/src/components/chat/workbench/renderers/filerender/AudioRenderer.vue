<template>
  <div class="audio-renderer h-full flex flex-col bg-muted/10 overflow-hidden">
    <!-- 音频播放器区域 -->
    <div class="flex-1 flex items-center justify-center relative p-8">
      <!-- 音频封面/图标 -->
      <div class="audio-cover flex flex-col items-center justify-center">
        <div class="w-24 h-24 rounded-full bg-primary/10 flex items-center justify-center mb-4">
          <Music class="w-12 h-12 text-primary/60" />
        </div>
        <h3 class="text-base font-medium text-foreground mb-1">{{ fileName }}</h3>
        <p v-if="duration" class="text-sm text-muted-foreground">
          {{ formatDuration(currentTime) }} / {{ formatDuration(duration) }}
        </p>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-background/80">
        <Loader2 class="w-8 h-8 animate-spin text-primary" />
      </div>

      <!-- 错误状态 -->
      <div v-if="error" class="absolute inset-0 flex flex-col items-center justify-center bg-background/90 text-destructive p-4">
        <AlertCircle class="w-12 h-12 mb-2" />
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

    <!-- 音频控制栏 -->
    <div class="flex-none px-6 py-4 bg-muted/20 border-t border-border">
      <!-- 进度条 -->
      <div class="flex items-center gap-3 mb-4">
        <span class="text-xs text-muted-foreground w-10 text-right font-mono">{{ formatDuration(currentTime) }}</span>
        <div class="flex-1 relative">
          <Slider
            :model-value="[progressValue]"
            :max="100"
            :step="0.1"
            @update:model-value="handleProgressChange"
          />
        </div>
        <span class="text-xs text-muted-foreground w-10 font-mono">{{ formatDuration(duration) }}</span>
      </div>

      <!-- 控制按钮 - 播放/暂停 + 音量 -->
      <div class="flex items-center justify-center">
        <!-- 占位，保持播放按钮居中 -->
        <div class="w-32"></div>

        <!-- 播放/暂停 -->
        <Button
          variant="default"
          size="icon"
          class="h-12 w-12 rounded-full"
          @click="togglePlay"
        >
          <Play v-if="!isPlaying" class="w-5 h-5 ml-0.5" />
          <Pause v-else class="w-5 h-5" />
        </Button>

        <!-- 音量控制 -->
        <div class="flex items-center gap-1.5 w-32 justify-end pl-4">
          <div class="w-16">
            <Slider
              :model-value="[volumeValue]"
              :max="100"
              :step="1"
              @update:model-value="handleVolumeChange"
            />
          </div>
          <Button
            variant="ghost"
            size="icon"
            class="h-8 w-8"
            @click="toggleMute"
          >
            <VolumeX v-if="isMuted || volumeValue === 0" class="w-4 h-4 text-muted-foreground" />
            <Volume1 v-else-if="volumeValue < 50" class="w-4 h-4 text-muted-foreground" />
            <Volume2 v-else class="w-4 h-4 text-muted-foreground" />
          </Button>
        </div>
      </div>
    </div>

    <!-- 隐藏的音频元素 -->
    <audio
      ref="audioRef"
      :src="audioUrl"
      @loadedmetadata="handleLoaded"
      @timeupdate="handleTimeUpdate"
      @ended="handleEnded"
      @error="handleError"
      @pause="isPlaying = false"
      @play="isPlaying = true"
    ></audio>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import {
  Play,
  Pause,
  Volume2,
  Volume1,
  VolumeX,
  Music,
  Loader2,
  AlertCircle,
  RefreshCw
} from 'lucide-vue-next'
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

const audioRef = ref(null)
const loading = ref(true)
const error = ref('')
const isPlaying = ref(false)
const duration = ref(0)
const currentTime = ref(0)
const volumeValue = ref(80)
const isMuted = ref(false)
const audioUrl = ref('')
const previousVolume = ref(80)

// 进度条值 (0-100)
const progressValue = computed(() => {
  if (!duration.value || duration.value === 0) return 0
  return (currentTime.value / duration.value) * 100
})

// 加载音频文件
const loadAudio = async () => {
  if (!props.filePath) return

  loading.value = true
  error.value = ''

  try {
    console.log('[AudioRenderer] Loading audio from:', props.filePath)

    // 使用 Tauri 的 readFile 读取音频文件
    const fileData = await readFile(props.filePath)
    console.log('[AudioRenderer] File data size:', fileData.length)

    // 根据文件扩展名确定 MIME 类型
    const ext = props.filePath.split('.').pop()?.toLowerCase()
    const mimeTypes = {
      'mp3': 'audio/mpeg',
      'wav': 'audio/wav',
      'ogg': 'audio/ogg',
      'm4a': 'audio/mp4',
      'aac': 'audio/aac',
      'flac': 'audio/flac',
      'wma': 'audio/x-ms-wma',
      'webm': 'audio/webm'
    }
    const mimeType = mimeTypes[ext] || 'audio/mpeg'

    // 创建 Blob 和 URL
    const blob = new Blob([fileData], { type: mimeType })
    const url = URL.createObjectURL(blob)
    audioUrl.value = url

    console.log('[AudioRenderer] Created blob URL:', url)
  } catch (e) {
    console.error('[AudioRenderer] Failed to load audio:', e)
    error.value = `音频加载失败: ${e.message || '无法读取文件'}`
    loading.value = false
  }
}

// 处理进度条变化
const handleProgressChange = (values) => {
  const value = values[0]
  if (!audioRef.value || !duration.value) return
  const newTime = (value / 100) * duration.value
  audioRef.value.currentTime = newTime
  currentTime.value = newTime
}

// 处理音量变化
const handleVolumeChange = (values) => {
  const value = values[0]
  if (!audioRef.value) return
  volumeValue.value = value
  audioRef.value.volume = value / 100
  isMuted.value = value === 0
  audioRef.value.muted = value === 0
}

// 播放/暂停切换
const togglePlay = () => {
  if (!audioRef.value) return

  if (isPlaying.value) {
    audioRef.value.pause()
  } else {
    audioRef.value.play()
  }
}

// 静音切换
const toggleMute = () => {
  if (!audioRef.value) return

  if (isMuted.value) {
    volumeValue.value = previousVolume.value || 80
    isMuted.value = false
    audioRef.value.muted = false
  } else {
    previousVolume.value = volumeValue.value
    volumeValue.value = 0
    isMuted.value = true
    audioRef.value.muted = true
  }
}

// 处理加载完成
const handleLoaded = () => {
  loading.value = false
  if (audioRef.value) {
    duration.value = audioRef.value.duration || 0
    audioRef.value.volume = volumeValue.value / 100
  }
}

// 处理时间更新
const handleTimeUpdate = () => {
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
  }
}

// 处理播放结束
const handleEnded = () => {
  isPlaying.value = false
  currentTime.value = 0
}

// 处理错误
const handleError = (e) => {
  console.error('[AudioRenderer] Audio load error:', e)
  error.value = `音频加载失败: 不支持的格式或文件损坏`
  loading.value = false
}

// 重试加载
const retryLoad = () => {
  loadAudio()
}

// 格式化时长
const formatDuration = (seconds) => {
  if (!seconds || isNaN(seconds)) return '0:00'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

onMounted(() => {
  loadAudio()
})

onUnmounted(() => {
  // 停止播放
  if (audioRef.value) {
    audioRef.value.pause()
    audioRef.value.src = ''
  }
  // 释放 blob URL
  if (audioUrl.value && audioUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(audioUrl.value)
  }
})
</script>

<style scoped>
.audio-renderer {
  min-height: 280px;
}

.audio-cover {
  animation: fadeIn 0.3s ease-in-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
