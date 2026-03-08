<template>
  <div class="text-preview h-full">
    <pre class="p-4 text-sm overflow-auto h-full"><code>{{ content }}</code></pre>
  </div>
</template>

<script setup>
const props = defineProps({
  content: {
    type: String,
    default: ''
  }
})
</script>
