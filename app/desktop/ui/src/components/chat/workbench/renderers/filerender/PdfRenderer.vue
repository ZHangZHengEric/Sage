<template>
  <div class="h-full w-full bg-muted/20 flex flex-col">
    <iframe
      v-if="blobUrl && !error"
      :src="blobUrl"
      class="w-full h-full border-0"
      title="PDF Viewer"
    ></iframe>

    <div v-else class="h-full flex flex-col items-center justify-center p-4 text-muted-foreground">
      <FileText class="w-16 h-16 mb-3 opacity-50" />
      <p class="text-sm mb-1">{{ t('workbench.pdf.title') }}</p>
      <p class="text-xs text-muted-foreground/60 mb-4">{{ error || t('workbench.pdf.loadingPreview') }}</p>
      <Button variant="outline" size="sm" @click="emit('open-file')">
        <ExternalLink class="w-4 h-4 mr-1" />
        {{ t('workbench.pdf.open') }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { FileText, ExternalLink } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { readFile } from '@tauri-apps/plugin-fs'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()

const props = defineProps({
  filePath: {
    type: String,
    default: ''
  }
})
const emit = defineEmits(['open-file'])

const blobUrl = ref('')
const error = ref('')

const cleanupBlobUrl = () => {
  if (blobUrl.value) {
    URL.revokeObjectURL(blobUrl.value)
    blobUrl.value = ''
  }
}

const loadPdfPreview = async () => {
  cleanupBlobUrl()
  error.value = ''
  if (!props.filePath) {
    error.value = t('workbench.pdf.noPath')
    return
  }

  try {
    const fileData = await readFile(props.filePath)
    if (!fileData || fileData.length < 8) {
      error.value = t('workbench.pdf.errorEmpty')
      return
    }

    const u8 = new Uint8Array(fileData)
    const decoder = new TextDecoder('ascii')
    const header = decoder.decode(u8.slice(0, Math.min(8, u8.length)))
    if (!header.startsWith('%PDF-')) {
      error.value = t('workbench.pdf.errorInvalidHeader')
      return
    }

    const tailBytes = u8.slice(Math.max(0, u8.length - 2048))
    const tail = decoder.decode(tailBytes)
    if (!tail.includes('%%EOF')) {
      error.value = t('workbench.pdf.errorMissingEof')
      return
    }

    const blob = new Blob([u8], { type: 'application/pdf' })
    blobUrl.value = URL.createObjectURL(blob)
  } catch (err) {
    error.value = t('workbench.pdf.errorLoad', { message: err?.message || 'Unknown' })
  }
}

watch(
  () => props.filePath,
  () => {
    loadPdfPreview()
  }
)

onMounted(() => {
  loadPdfPreview()
})

onUnmounted(() => {
  cleanupBlobUrl()
})
</script>
