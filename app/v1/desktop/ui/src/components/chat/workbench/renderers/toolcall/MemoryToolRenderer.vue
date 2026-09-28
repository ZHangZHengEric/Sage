<template>
  <div class="memory-renderer h-full flex flex-col overflow-hidden bg-background">
    <!-- 头部：显示搜索词和结果数 -->
    <div class="px-4 py-3 border-b flex items-center gap-2 flex-none">
      <Brain class="w-4 h-4 text-primary" />
      <span v-if="memoryQuery" class="text-sm font-medium truncate">{{ memoryQuery }}</span>
      <span v-else class="text-sm font-medium">{{ t('workbench.tool.memorySearch') }}</span>
      <Badge v-if="totalResults > 0" variant="secondary" class="text-xs">
        {{ totalResults }}
      </Badge>
    </div>

    <!-- 内容 -->
    <div class="flex-1 overflow-auto p-4">
      <!-- 加载中 -->
      <div v-if="loading" class="flex items-center justify-center h-full text-muted-foreground">
        <Brain class="w-6 h-6 animate-pulse mr-2" />
        {{ t('workbench.tool.searchingMemory') }}
      </div>

      <!-- 无结果 -->
      <div v-else-if="totalResults === 0" class="flex items-center justify-center h-full text-muted-foreground">
        {{ t('workbench.tool.noMemoryResults') }}
      </div>

      <!-- 结果列表 -->
      <div v-else class="space-y-3">
        <div
          v-for="(result, index) in allResults"
          :key="index"
          class="border rounded-lg p-4 hover:bg-muted/30 transition-colors"
        >
          <!-- 文件 -->
          <template v-if="result.type === 'file'">
            <div class="flex items-start gap-3">
              <FileText class="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" />
              <div class="flex-1 min-w-0">
                <div class="font-medium text-sm">{{ getFileName(result.path) }}</div>
                <div class="text-xs text-muted-foreground mt-0.5">{{ getFilePath(result.path) }}</div>
                
                <!-- 代码片段 -->
                <div v-if="result.snippets && result.snippets.length" class="mt-3 space-y-2">
                  <div
                    v-for="(snippet, sidx) in result.snippets"
                    :key="sidx"
                    class="bg-muted rounded-md p-3 text-sm"
                  >
                    <div class="text-xs text-muted-foreground mb-1">{{ t('workbench.tool.line') }} {{ snippet.line_number }}</div>
                    <pre class="text-sm font-mono whitespace-pre-wrap">{{ snippet.text }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 对话 -->
          <template v-else>
            <div class="flex items-start gap-3">
              <div
                class="w-5 h-5 rounded flex items-center justify-center flex-shrink-0 mt-0.5"
                :class="result.role === 'user' ? 'bg-amber-100' : 'bg-green-100'"
              >
                <User v-if="result.role === 'user'" class="w-3 h-3 text-amber-600" />
                <Bot v-else class="w-3 h-3 text-green-600" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-sm font-medium">{{ result.role === 'user' ? t('workbench.tool.you') : t('workbench.tool.assistant') }}</span>
                  <span v-if="result.timestamp" class="text-xs text-muted-foreground">{{ formatTime(result.timestamp) }}</span>
                </div>
                <div class="text-sm text-foreground/80">{{ result.content_preview }}</div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '@/utils/i18n.js'
import { Brain, FileText, User, Bot } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'

const props = defineProps({
  toolCall: { type: Object, required: true },
  toolResult: { type: [Object, String], default: null }
})

const { t } = useLanguage()

const parsedResult = computed(() => {
  if (!props.toolResult) return null
  let result = props.toolResult
  if (typeof result === 'string') {
    try {
      result = JSON.parse(result)
    } catch {
      return null
    }
  }
  if (result.content && typeof result.content === 'object') return result.content
  return result
})

const loading = computed(() => !props.toolResult)

const memoryQuery = computed(() => {
  // 尝试多种路径获取参数
  const args = props.toolCall?.function?.arguments || 
               props.toolCall?.arguments ||
               props.toolCall?.data?.function?.arguments ||
               props.toolCall?.data?.arguments
  
  if (!args) return ''
  try {
    const parsed = typeof args === 'string' ? JSON.parse(args) : args
    return parsed.query || ''
  } catch {
    return ''
  }
})

const allResults = computed(() => {
  const results = []
  const files = parsedResult.value?.long_term_memory ||
    (parsedResult.value?.results || []).filter(r => r.type === 'file')
  files.forEach(f => results.push({ ...f, type: 'file' }))
  const chats = parsedResult.value?.session_history ||
    (parsedResult.value?.results || []).filter(r => r.type === 'history')
  chats.forEach(c => results.push({ ...c, type: 'history' }))
  return results
})

const totalResults = computed(() => allResults.value.length)

const getFileName = (path) => path?.split('/').pop() || ''
const getFilePath = (path) => {
  if (!path) return ''
  const parts = path.split('/')
  parts.pop()
  return parts.join('/')
}

const formatTime = (ts) => {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
/* Memory tool specific styles */
</style>
