<template>
  <div class="h-full flex flex-col">
    <div class="file-header px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
      <FileText class="w-4 h-4" />
      <span class="font-medium text-sm">{{ writeFilePath || unknownFileLabel }}</span>
      <Badge variant="secondary" class="text-xs">{{ writeFileType }}</Badge>
      <Badge v-if="writeModeLabel" variant="outline" class="text-xs">{{ writeModeLabel }}</Badge>
    </div>
    <div class="write-info px-4 py-2 text-sm text-muted-foreground flex-none border-b border-border">
      {{ t('workbench.tool.writtenBytes', { bytes: writeContentLength }) }}
    </div>
    <div class="file-content flex-1 overflow-auto p-4">
      <div v-if="!writeContent" class="flex h-full items-center justify-center text-muted-foreground text-sm">
        <Loader2 class="w-4 h-4 mr-2 animate-spin" />
        <span>{{ t('workbench.tool.loading') }}</span>
      </div>
      <SyntaxHighlighter
        v-else-if="isCodeFile(writeFileType)"
        :code="writeContent"
        :language="writeFileType"
      />
      <MarkdownRenderer
        v-else-if="writeFileType === 'markdown'"
        :content="writeContent"
      />
      <pre v-else class="whitespace-pre-wrap text-sm">{{ writeContent }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FileText, Loader2 } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import SyntaxHighlighter from '@/components/chat/SyntaxHighlighter.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { useLanguage } from '@/utils/i18n'

const { t } = useLanguage()
const unknownFileLabel = computed(() => t('workbench.tool.unknownFile') || 'Unknown file')
const appendModeLabel = computed(() => t('workbench.tool.fileWrite.mode.append') || 'Append')
const overwriteModeLabel = computed(() => t('workbench.tool.fileWrite.mode.overwrite') || 'Overwrite')

const props = defineProps({
  toolArgs: {
    type: Object,
    default: () => ({})
  },
  toolResult: {
    type: Object,
    default: null
  }
})

const writeFilePath = computed(() => props.toolArgs.file_path || props.toolArgs.path || '')
const writeFileType = computed(() => {
  const ext = writeFilePath.value.split('.').pop()?.toLowerCase()
  const typeMap = {
    py: 'python',
    js: 'javascript',
    ts: 'typescript',
    vue: 'vue',
    html: 'html',
    css: 'css',
    json: 'json',
    md: 'markdown',
    txt: 'text',
    yml: 'yaml',
    yaml: 'yaml',
    sh: 'bash'
  }
  return typeMap[ext] || ext || 'text'
})
const writeContent = computed(() => {
  return props.toolArgs.content || props.toolArgs.text || props.toolArgs.body || ''
})
const writeContentLength = computed(() => writeContent.value ? new Blob([writeContent.value]).size : 0)
const writeModeLabel = computed(() => {
  const mode = props.toolArgs.mode || props.toolArgs.operation || ''
  if (!mode) return ''
  return mode === 'append' ? appendModeLabel.value : overwriteModeLabel.value
})

const isCodeFile = (type) => ['python', 'javascript', 'typescript', 'vue', 'html', 'css', 'json', 'yaml', 'bash'].includes(type)
</script>
