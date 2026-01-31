<template>
  <div class="w-[400px] flex flex-col border-l bg-background">
    <div class="flex items-center justify-between p-4 border-b">
      <h3 class="text-base font-semibold">{{ t('chat.toolDetails') }}</h3>
      <Button variant="ghost" size="icon" @click="$emit('close')">
        <X class="h-4 w-4" />
      </Button>
    </div>
    <ScrollArea class="flex-1">
      <div class="p-4 space-y-6">
        <div class="space-y-2">
          <h4 class="text-sm font-medium text-muted-foreground">{{ t('chat.toolName') }}</h4>
          <p class="text-sm font-medium">{{ toolExecution.function.name }}</p>
        </div>
        
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <h4 class="text-sm font-medium text-muted-foreground">{{ t('chat.toolParams') }}</h4>
            <div class="flex items-center gap-2">
              <span v-if="copiedParams" class="text-xs text-green-500 animate-in fade-in slide-in-from-right-2">Copied!</span>
              <Button variant="ghost" size="icon" class="h-6 w-6" @click="copyParams">
                <Copy class="h-3 w-3" />
              </Button>
            </div>
          </div>
          <Card class="bg-muted/50 border-muted">
            <pre class="p-4 text-xs font-mono whitespace-pre-wrap break-all overflow-auto max-h-[300px]">{{ formatJsonParams(toolExecution.function.arguments) }}</pre>
          </Card>
        </div>

        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <h4 class="text-sm font-medium text-muted-foreground">{{ t('chat.toolResult') }}</h4>
            <div class="flex items-center gap-2">
              <span v-if="copiedResult" class="text-xs text-green-500 animate-in fade-in slide-in-from-right-2">Copied!</span>
              <Button variant="ghost" size="icon" class="h-6 w-6" @click="copyResult">
                <Copy class="h-3 w-3" />
              </Button>
            </div>
          </div>
          <Card class="bg-muted/50 border-muted">
            <pre class="p-4 text-xs font-mono whitespace-pre-wrap break-all overflow-auto max-h-[300px]">{{ formatJsonParams(formatToolResult(toolResult)) }}</pre>
          </Card>
        </div>
      </div>
    </ScrollArea>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useLanguage } from '@/utils/i18n.js'
import { Copy, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'

// 使用国际化
const { t } = useLanguage()

// 定义 props
const props = defineProps({
  toolExecution: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [String, Object, Array],
    default: null
  }
})

// 定义 emits
const emit = defineEmits(['close'])

const copiedParams = ref(false)
const copiedResult = ref(false)

// 复制到剪贴板
const copyToClipboard = async (text, type) => {
  try {
    await navigator.clipboard.writeText(text)
    if (type === 'params') {
      copiedParams.value = true
      setTimeout(() => copiedParams.value = false, 2000)
    } else {
      copiedResult.value = true
      setTimeout(() => copiedResult.value = false, 2000)
    }
  } catch (err) {
    console.error('复制失败:', err)
  }
}

const copyParams = () => {
  copyToClipboard(formatJsonParams(props.toolExecution.function.arguments), 'params')
}

const copyResult = () => {
  copyToClipboard(formatJsonParams(formatToolResult(props.toolResult)), 'result')
}

// 格式化工具结果
const formatToolResult = (result) => {
  if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result)
      return parsed.content || result
    } catch {
      return result
    }
  } else if (result && typeof result === 'object') {
    return result.content || JSON.stringify(result, null, 2)
  }
  return JSON.stringify(result, null, 2)
}

// 格式化JSON参数显示
const formatJsonParams = (params) => {
  if (typeof params === 'string') {
    try {
      const parsed = JSON.parse(params)
      return JSON.stringify(parsed, null, 2)
    } catch {
      return params
    }
  } else if (params && typeof params === 'object') {
    return JSON.stringify(params, null, 2)
  }
  return String(params)
}
</script>

<style scoped>
/* Removed custom styles in favor of Tailwind classes */
</style>