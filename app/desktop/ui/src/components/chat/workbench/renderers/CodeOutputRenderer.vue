<template>
  <div class="code-output-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-xl">🖥️</span>
        <span class="text-sm font-medium">{{ t('workbench.codeOutput.title') }}</span>
        <Badge variant="secondary" class="text-xs">{{ language || 'text' }}</Badge>
      </div>
      <div class="flex items-center gap-1 flex-shrink-0">
        <Button
          v-if="code"
          variant="ghost"
          size="sm"
          @click="copyCode"
          class="h-7 px-2"
        >
          <Check v-if="copied" class="w-4 h-4 mr-1 text-green-500" />
          <Copy v-else class="w-4 h-4 mr-1" />
          {{ copied ? t('common.copied') : t('common.copy') }}
        </Button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="flex-1 overflow-y-auto p-4">
      <!-- 代码部分 -->
      <div v-if="code" class="mb-4">
        <SyntaxHighlighter :code="code" :language="language" :show-header="false" :show-copy-button="false" />
      </div>

      <!-- 输出部分 -->
      <div v-if="output">
        <pre class="bg-muted/50 p-4 rounded-lg text-sm overflow-x-auto whitespace-pre-wrap font-mono">{{ output }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Copy, Check } from 'lucide-vue-next'
import SyntaxHighlighter from '../../SyntaxHighlighter.vue'

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

const copied = ref(false)

// 从 item 中提取代码和输出信息
const code = computed(() => {
  return props.item.data?.code || ''
})

const language = computed(() => {
  return props.item.data?.language || 'text'
})

const output = computed(() => {
  return props.item.data?.output || ''
})

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': 'AI',
    'user': '用户',
    'system': '系统',
    'tool': '工具'
  }
  return roleMap[props.item?.role] || 'AI'
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${hours}:${minutes}:${seconds}`
}

const copyCode = async () => {
  if (!code.value) return
  try {
    await navigator.clipboard.writeText(code.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
  }
}
</script>
