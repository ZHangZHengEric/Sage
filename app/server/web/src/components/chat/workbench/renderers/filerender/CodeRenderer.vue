<template>
  <div class="code-preview h-full min-h-0 overflow-hidden p-4">
    <SyntaxHighlighter
      :code="content"
      :language="language"
      :show-header="true"
      :show-copy-button="true"
      class="h-full min-h-0"
    />
  </div>
</template>

<script setup>
import SyntaxHighlighter from '@/components/chat/SyntaxHighlighter.vue'

const props = defineProps({
  content: {
    type: String,
    default: ''
  },
  language: {
    type: String,
    default: 'text'
  }
})
</script>
