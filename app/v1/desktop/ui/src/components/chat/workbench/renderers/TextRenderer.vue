<template>
  <div class="text-renderer h-full overflow-auto p-4">
    <MarkdownRenderer v-if="isMarkdown" :content="content" />
    <pre v-else class="whitespace-pre-wrap text-sm font-mono">{{ content }}</pre>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownRenderer from '../../MarkdownRenderer.vue'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

// 从 item 中提取内容
const content = computed(() => {
  return props.item.data?.content || ''
})

const isMarkdown = computed(() => {
  return props.item.type === 'markdown'
})
</script>
