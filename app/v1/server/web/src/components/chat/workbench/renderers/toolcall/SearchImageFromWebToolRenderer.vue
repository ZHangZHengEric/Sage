<template>
  <div class="search-image-container h-full flex flex-col overflow-hidden">
    <div class="search-header px-4 py-3 border-b border-border/30 bg-muted/20 flex-none">
      <div class="flex items-center gap-2">
        <ImageIcon class="w-4 h-4 text-primary" />
        <span class="text-sm font-medium">{{ searchImageQuery }}</span>
        <Badge v-if="searchImageResults.length > 0" variant="secondary" class="text-xs">
          {{ searchImageResults.length }} {{ t('workbench.tool.images') }}
        </Badge>
      </div>
    </div>
    <div class="search-image-results flex-1 overflow-auto p-4">
      <div v-if="searchImageLoading" class="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 class="w-5 h-5 animate-spin mr-2" />
        {{ t('workbench.tool.searchingImages') }}
      </div>
      <div v-else-if="searchImageResults.length === 0" class="flex items-center justify-center h-full text-muted-foreground">
        <div class="text-center">
          <ImageIcon class="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p class="text-sm">{{ t('workbench.tool.noImageResults') }}</p>
        </div>
      </div>
      <div v-else class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        <div
          v-for="(image, index) in searchImageResults"
          :key="index"
          class="search-image-item relative group aspect-square rounded-lg overflow-hidden border hover:border-primary transition-colors cursor-pointer"
          @click="openImagePreview(image.image_url || image.url)"
        >
          <img
            :src="image.image_url || image.url"
            :alt="image.title"
            class="w-full h-full object-cover"
            @error="handleImageError"
          />
          <div class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2">
            <p class="text-xs text-white truncate">{{ image.title }}</p>
            <p class="text-[10px] text-white/70 truncate">{{ image.source }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Image as ImageIcon, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const searchImageQuery = computed(() => props.toolArgs.query || '')
const searchImageLoading = computed(() => !props.toolResult)
const searchImageResults = computed(() => {
  if (!props.toolResult) return []
  try {
    const parsed = typeof props.toolResult.content === 'string' ? JSON.parse(props.toolResult.content) : props.toolResult.content
    if (parsed.images && Array.isArray(parsed.images)) return parsed.images
    if (parsed.results && Array.isArray(parsed.results)) return parsed.results
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
})
const openImagePreview = (url) => { if (url) window.open(url, '_blank') }
const handleImageError = (event) => {
  event.target.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"%3E%3Crect width="100" height="100" fill="%23f3f4f6"/%3E%3Ctext x="50" y="50" font-family="Arial" font-size="12" fill="%239ca3af" text-anchor="middle" dy=".3em"%3EImage Error%3C/text%3E%3C/svg%3E'
}
</script>
