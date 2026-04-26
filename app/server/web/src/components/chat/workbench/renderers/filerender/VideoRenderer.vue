<template>
  <div class="h-full flex flex-col bg-black overflow-hidden">
    <div class="flex-1 flex items-center justify-center relative overflow-hidden min-h-0">
      <video
        v-if="videoUrl && !hasError"
        ref="videoRef"
        :src="videoUrl"
        class="max-w-full max-h-full w-full h-full object-contain outline-none"
        controls
        preload="metadata"
        @error="hasError = true"
        @loadedmetadata="onLoaded"
      />
      <div v-if="hasError" class="flex flex-col items-center gap-3 text-white/70 p-6">
        <VideoOff class="w-12 h-12 opacity-40" />
        <p class="text-sm text-center">视频无法播放</p>
      </div>
    </div>
    <div class="flex-none px-4 py-2 bg-black/80 border-t border-white/10 flex items-center justify-between">
      <div class="flex items-center gap-2 text-xs text-white/60 min-w-0">
        <Film class="w-3.5 h-3.5 flex-shrink-0" />
        <span class="truncate">{{ fileName }}</span>
      </div>
      <span v-if="durationLabel" class="text-xs text-white/50">{{ durationLabel }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Film, VideoOff } from 'lucide-vue-next'

const props = defineProps({
  fileUrl: { type: String, default: '' },
  fileName: { type: String, default: '' }
})

const videoRef = ref(null)
const hasError = ref(false)
const duration = ref(0)

const videoUrl = computed(() => props.fileUrl || '')

const durationLabel = computed(() => {
  const s = duration.value
  if (!s || isNaN(s)) return ''
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
})

const onLoaded = () => {
  if (videoRef.value) duration.value = videoRef.value.duration
}
</script>
