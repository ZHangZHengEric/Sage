<template>
  <div class="search-web-container h-full flex flex-col overflow-hidden">
    <div class="search-header px-4 py-3 border-b border-border/30 bg-muted/20 flex-none">
      <div class="flex items-center gap-2">
        <Search class="w-4 h-4 text-primary" />
        <span class="text-sm font-medium">{{ searchQuery }}</span>
        <Badge v-if="searchResults.length > 0" variant="secondary" class="text-xs">
          {{ searchResults.length }} {{ t('workbench.tool.results') }}
        </Badge>
      </div>
    </div>
    <div class="search-results flex-1 overflow-auto p-4 space-y-3">
      <div v-if="searchLoading" class="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 class="w-5 h-5 animate-spin mr-2" />
        {{ t('workbench.tool.searching') }}
      </div>
      <div v-else-if="searchResults.length === 0" class="flex items-center justify-center h-full text-muted-foreground">
        <div class="text-center">
          <Search class="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p class="text-sm">{{ t('workbench.tool.noSearchResults') }}</p>
        </div>
      </div>
      <div
        v-for="(result, index) in searchResults"
        :key="index"
        class="search-result-item border rounded-lg p-3 hover:bg-muted/30 transition-colors cursor-pointer"
        @click="openSearchResult(result.url)"
      >
        <div class="flex items-start gap-3">
          <div class="flex-1 min-w-0">
            <h4 class="text-sm font-medium text-primary truncate">{{ result.title }}</h4>
            <p class="text-xs text-muted-foreground mt-1 line-clamp-2">{{ result.content }}</p>
            <div class="flex items-center gap-2 mt-2">
              <Globe class="w-3 h-3 text-muted-foreground" />
              <span class="text-xs text-muted-foreground truncate">{{ result.url }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Search, Loader2, Globe } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null }
})

const searchQuery = computed(() => props.toolArgs.query || '')
const searchLoading = computed(() => !props.toolResult)
const searchResults = computed(() => {
  if (!props.toolResult) return []
  try {
    const parsed = typeof props.toolResult.content === 'string' ? JSON.parse(props.toolResult.content) : props.toolResult.content
    if (parsed.results && Array.isArray(parsed.results)) return parsed.results
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
})
const openSearchResult = (url) => { if (url) window.open(url, '_blank') }
</script>
