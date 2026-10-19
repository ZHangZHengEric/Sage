<script setup>
import { computed, ref } from 'vue'
import { renderMessageMarkdown } from '../agui/markdown.js'
const props = defineProps({ text: { type: String, default: '' } })
const html = computed(() => renderMessageMarkdown(props.text)), feedback = ref('')
async function copyCode(event) {
  const trigger = event.target.closest('button[data-copy-code]')
  if (!trigger || !event.currentTarget.contains(trigger)) return
  try { await navigator.clipboard.writeText(trigger.closest('.message-code').querySelector('code').textContent); feedback.value = '代码已复制' }
  catch { feedback.value = '复制失败，请选择代码后复制' }
}
</script>
<template><div class="message-body"><div class="md" @click="copyCode" v-html="html" /><span v-if="feedback" class="message-copy-feedback" role="status">{{ feedback }}</span></div></template>
