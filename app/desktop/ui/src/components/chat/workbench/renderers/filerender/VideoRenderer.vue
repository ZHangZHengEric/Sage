<template>
  <div class="video-renderer h-full flex flex-col bg-black overflow-hidden">
    <!-- 播放器区域 -->
    <div class="flex-1 flex items-center justify-center relative overflow-hidden min-h-0">
      <video
        v-if="videoUrl && !error"
        ref="videoRef"
        :src="videoUrl"
        class="video-element"
        controls
        preload="metadata"
        @error="handleError"
        @loadedmetadata="handleLoaded"
        @waiting="buffering = true"
        @playing="buffering = false"
        @canplay="buffering = false"
      />

      <!-- 缓冲/加载 -->
      <div
        v-if="loading || buffering"
        class="absolute inset-0 flex items-center justify-center bg-black/60 pointer-events-none"
      >
        <Loader2 class="w-8 h-8 animate-spin text-white/80" />
      </div>

      <!-- 错误 -->
      <div v-if="error" class="absolute inset-0 flex flex-col items-center justify-center bg-black text-white p-6 gap-3">
        <VideoOff class="w-12 h-12 text-white/40" />
        <p class="text-sm text-white/70 text-center">{{ error }}</p>
        <Button variant="outline" size="sm" class="text-white border-white/30 hover:bg-white/10" @click="retryLoad">
          <RefreshCw class="w-4 h-4 mr-1" />
          重试
        </Button>
      </div>
    </div>

    <!-- 底部信息栏 -->
    <div class="flex-none px-4 py-2 bg-black/80 border-t border-white/10 flex items-center justify-between gap-4">
      <div class="flex items-center gap-2 text-xs text-white/60 min-w-0">
        <Film class="w-3.5 h-3.5 flex-shrink-0" />
        <span class="truncate" :title="fileName">{{ fileName }}</span>
        <Badge variant="outline" class="text-[10px] border-white/20 text-white/50 flex-shrink-0">{{ extLabel }}</Badge>
      </div>
      <div v-if="durationLabel" class="text-xs text-white/50 flex-shrink-0">{{ durationLabel }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, Film, VideoOff, RefreshCw } from 'lucide-vue-next'
import request from '@/utils/request.js'

const props = defineProps({
  filePath: { type: String, required: true },
  fileName: { type: String, default: '' }
})

const videoRef = ref(null)
const loading = ref(true)
const buffering = ref(false)
const error = ref('')
const duration = ref(0)
const videoUrl = ref('')

// 文件扩展名 → MIME 类型
const MIME_MAP = {
  mp4: 'video/mp4',
  webm: 'video/webm',
  mov: 'video/quicktime',
  m4v: 'video/mp4',
  mkv: 'video/x-matroska',
  avi: 'video/x-msvideo',
  flv: 'video/x-flv',
  ogv: 'video/ogg',
}

const ext = computed(() => {
  const name = props.filePath || props.fileName || ''
  return (name.split('.').pop() || '').toLowerCase()
})
const extLabel = computed(() => ext.value.toUpperCase() || 'VIDEO')
const mimeType = computed(() => MIME_MAP[ext.value] || 'video/mp4')

const durationLabel = computed(() => {
  const s = duration.value
  if (!s || isNaN(s)) return ''
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
})

// 从绝对路径中解析 agentId 和相对路径
// 路径格式：/Users/.../.sage/agents/{agentId}/{relativePath}
const parseAgentPath = (absPath) => {
  const match = absPath.match(/\/agents\/([^/]+)\/(.+)$/)
  if (match) return { agentId: match[1], relativePath: match[2] }
  return null
}

// 构建视频 URL：优先通过后端 stream 接口，支持 Range 请求
const buildVideoUrl = async (path) => {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path

  const clean = path.replace(/^file:\/\//i, '')
  const parsed = parseAgentPath(clean)
  if (parsed) {
    // Use the dynamically-resolved baseURL (updated by App.vue after sage-desktop-ready),
    // falling back to the build-time env prefix only as a last resort.
    const baseURL = request.baseURL || import.meta.env.VITE_BACKEND_API_PREFIX || ''
    return `${baseURL}/api/agent/${parsed.agentId}/file_workspace/stream?file_path=${encodeURIComponent(parsed.relativePath)}`
  }

  // 降级：非 agent 工作区路径，使用 Tauri asset 协议
  try {
    const { convertFileSrc } = await import('@tauri-apps/api/core')
    return convertFileSrc(clean)
  } catch {
    return path
  }
}

const loadVideo = async () => {
  if (!props.filePath) return
  loading.value = true
  error.value = ''
  videoUrl.value = ''

  try {
    videoUrl.value = await buildVideoUrl(props.filePath)
  } catch (e) {
    error.value = `视频加载失败: ${e?.message || '无法读取文件'}`
    loading.value = false
  }
}

const handleLoaded = () => {
  loading.value = false
  if (videoRef.value) duration.value = videoRef.value.duration
}

const handleError = (e) => {
  const msg = e?.target?.error?.message || '不支持的格式或文件损坏'
  error.value = `视频播放失败: ${msg}`
  loading.value = false
}

const retryLoad = () => loadVideo()

onMounted(() => loadVideo())

watch(() => props.filePath, (newPath, oldPath) => {
  if (newPath && newPath !== oldPath) loadVideo()
})

onUnmounted(() => {
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
})
</script>

<style scoped>
.video-element {
  max-width: 100%;
  max-height: 100%;
  width: 100%;
  height: 100%;
  object-fit: contain;
  outline: none;
}

/* 控制条渐变背景 */
.video-element::-webkit-media-controls-enclosure {
  background: linear-gradient(to top, rgba(0,0,0,0.6) 0%, transparent 100%);
}

.video-element::-webkit-media-controls-panel {
  background: transparent;
}

/* 进度条 */
.video-element::-webkit-media-controls-timeline {
  background-color: rgba(255,255,255,0.25);
  border-radius: 4px;
  height: 3px;
}

/* 时间文字 */
.video-element::-webkit-media-controls-current-time-display,
.video-element::-webkit-media-controls-time-remaining-display {
  color: #fff;
  font-size: 12px;
  text-shadow: 0 1px 2px rgba(0,0,0,0.6);
}
</style>
