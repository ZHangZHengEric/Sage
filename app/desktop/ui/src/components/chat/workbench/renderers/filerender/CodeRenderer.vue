<template>
  <div class="code-preview h-full">
    <MermaidRenderer
      v-if="isMermaid"
      :code="content"
    />
    <SyntaxHighlighter
      v-else
      :code="content"
      :language="language"
      :show-header="showHeader"
      :show-copy-button="showCopyButton"
      class="h-full"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import SyntaxHighlighter from '@/components/chat/SyntaxHighlighter.vue'
import MermaidRenderer from './MermaidRenderer.vue'
import { isMermaidLanguage } from './drawio'

const props = defineProps({
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

const isMermaid = computed(() => !!props.content && isMermaidLanguage(props.language))
</script>
