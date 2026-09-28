<template>
  <div class="mb-4 w-full max-w-4xl mx-auto">
    <div class="flex items-center justify-between mb-2">
      <h2 class="text-sm font-medium text-foreground flex items-center gap-2">
        <span>{{ t('chat.abilities.panelTitle') }}</span>
      </h2>
      <div class="flex items-center gap-1">
        <button
          v-if="hasResults"
          type="button"
          class="inline-flex items-center justify-center rounded-full p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors"
          :title="t('chat.abilities.regenerate')"
          @click="$emit('refresh')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
            <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
            <path d="M16 21h5v-5" />
          </svg>
        </button>
        <button
          type="button"
          class="inline-flex items-center justify-center rounded-full p-1 text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-colors"
          @click="$emit('close')"
          :title="t('chat.abilities.close') || 'Close'"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            class="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </div>

    <div class="border border-border bg-muted/40 rounded-xl p-3 sm:p-4">
      <div v-if="loading" class="flex items-center gap-2 text-sm text-muted-foreground">
        <span class="inline-flex h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-muted-foreground" />
        <span>{{ t('chat.abilities.loading') }}</span>
      </div>

      <div v-else-if="error" class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-sm">
        <div class="text-destructive flex-1">
          {{ displayError }}
        </div>
        <button
          type="button"
          class="inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          @click="$emit('retry')"
        >
          {{ t('chat.abilities.retry') }}
        </button>
      </div>

      <div v-else-if="!items || items.length === 0" class="text-sm text-muted-foreground">
        {{ t('chat.abilities.empty') }}
      </div>

      <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <button
          v-for="item in items"
          :key="item.id || item.title"
          type="button"
          class="group text-left border border-border/70 rounded-lg px-3 py-2.5 bg-background/60 hover:bg-accent hover:border-accent transition-colors flex flex-col gap-1.5"
          @click="$emit('select', item)"
        >
          <div class="text-sm font-medium text-foreground group-hover:text-accent-foreground truncate">
            {{ item.title }}
          </div>
          <div class="text-xs text-muted-foreground group-hover:text-accent-foreground/90 line-clamp-3">
            {{ item.description }}
          </div>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  items: {
    type: Array,
    required: true
  },
  loading: {
    type: Boolean,
    default: false
  },
  error: {
    type: [String, Object, null],
    default: null
  }
})

const emit = defineEmits(['close', 'retry', 'select', 'refresh'])

const hasResults = computed(() => !props.loading && !props.error && props.items?.length > 0)

const { t } = useLanguage()

const displayError = computed(() => {
  if (!props.error) return ''
  if (typeof props.error === 'string') return t(props.error) || props.error
  if (props.error?.message) return props.error.message
  return t('chat.abilities.error') || '获取能力列表失败'
})
</script>
