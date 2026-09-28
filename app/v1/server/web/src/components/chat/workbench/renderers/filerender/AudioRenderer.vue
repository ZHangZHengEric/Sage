<template>
  <div class="audio-renderer h-full min-h-[240px] flex flex-col overflow-hidden bg-muted/10">
    <div class="flex-1 min-h-0 flex items-center justify-center p-6">
      <div class="w-full max-w-xl rounded-lg border border-border bg-background/80 p-5 shadow-sm">
        <div class="mb-4 flex min-w-0 items-center gap-3">
          <div class="flex h-12 w-12 flex-none items-center justify-center rounded-full bg-primary/10">
            <Music class="h-6 w-6 text-primary" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-foreground">{{ fileName }}</p>
            <p v-if="durationLabel" class="text-xs text-muted-foreground">{{ durationLabel }}</p>
          </div>
        </div>

        <audio
          v-if="audioUrl && !hasError"
          ref="audioRef"
          :src="audioUrl"
          class="w-full"
          controls
          preload="metadata"
          @loadedmetadata="handleLoadedMetadata"
          @error="hasError = true"
        />

        <div v-else class="flex min-h-12 items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertCircle class="h-4 w-4 flex-none" />
          <span>音频无法播放</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { AlertCircle, Music } from 'lucide-vue-next'

const props = defineProps({
  fileUrl: {
    type: String,
    default: ''
  },
  fileName: {
    type: String,
    default: ''
  }
})

const audioRef = ref(null)
const duration = ref(0)
const hasError = ref(false)

const audioUrl = computed(() => props.fileUrl || '')

const durationLabel = computed(() => {
  const seconds = duration.value
  if (!seconds || isNaN(seconds)) return ''
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  return `${minutes}:${String(rest).padStart(2, '0')}`
})

const handleLoadedMetadata = () => {
  if (!audioRef.value) return
  duration.value = audioRef.value.duration || 0
}

watch(audioUrl, () => {
  hasError.value = false
  duration.value = 0
})
</script>
