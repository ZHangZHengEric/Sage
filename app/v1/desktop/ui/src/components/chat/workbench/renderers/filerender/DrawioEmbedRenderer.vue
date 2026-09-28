<template>
  <div class="drawio-embed-renderer h-full min-h-0 overflow-hidden rounded-xl border border-border/60 bg-background/80">
    <div v-if="error" class="flex h-full items-center justify-center p-4 text-sm text-destructive">
      {{ error }}
    </div>
    <iframe
      v-else
      ref="iframeRef"
      :src="iframeSrc"
      class="h-full w-full border-0"
      title="draw.io preview"
      loading="lazy"
      referrerpolicy="no-referrer"
      sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-downloads"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  xml: {
    type: String,
    default: ''
  }
})

const iframeRef = ref(null)
const error = ref('')
const iframeSrc = computed(() => 'https://embed.diagrams.net/?embed=1&proto=json&spin=1&ui=min&libraries=0&saveAndExit=0&noSaveBtn=1')

const postLoadMessage = () => {
  if (!iframeRef.value?.contentWindow || !props.xml) return
  iframeRef.value.contentWindow.postMessage(JSON.stringify({
    action: 'load',
    xml: props.xml,
    autosave: 0
  }), 'https://embed.diagrams.net')
}

const handleMessage = (event) => {
  if (event.origin !== 'https://embed.diagrams.net') return

  let payload = event.data
  if (typeof payload === 'string') {
    try {
      payload = JSON.parse(payload)
    } catch (parseError) {
      payload = { event: payload }
    }
  }

  if (payload?.event === 'init' || payload?.event === 'ready') {
    postLoadMessage()
  }

  if (payload?.event === 'exit' || payload?.event === 'save') {
    postLoadMessage()
  }
}

watch(() => props.xml, () => {
  error.value = props.xml ? '' : '未提供 draw.io XML 内容'
  postLoadMessage()
}, { immediate: true })

onMounted(() => {
  window.addEventListener('message', handleMessage)
})

onUnmounted(() => {
  window.removeEventListener('message', handleMessage)
})
</script>
