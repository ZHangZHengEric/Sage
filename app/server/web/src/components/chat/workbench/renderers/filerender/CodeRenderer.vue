<template>
  <div class="code-preview h-full min-h-0 overflow-hidden p-4">
    <SyntaxHighlighter
      :code="content"
      :language="language"
      :show-header="showHeader"
      :show-copy-button="showCopyButton"
      class="h-full min-h-0"
    />
  </div>
</template>

<script setup>
import SyntaxHighlighter from '@/components/chat/SyntaxHighlighter.vue'

defineProps({
  content: {
    type: String,
    default: ''
  },
  language: {
    type: String,
    default: 'text'
  },
  showHeader: {
    type: Boolean,
    default: true
  },
  showCopyButton: {
    type: Boolean,
    default: true
  }
})
</script>
