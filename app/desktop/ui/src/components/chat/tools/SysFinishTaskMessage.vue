<template>
  <div 
    class="sys-finish-task-message w-full max-w-[800px] mb-1.5 rounded-lg border bg-card/50 overflow-hidden transition-all hover:border-border/80 cursor-pointer"
    @click="handleClick"
  >
    <!-- Header Section - 更紧凑 -->
    <div class="flex items-center justify-between px-2.5 py-1.5 border-b bg-muted/20">
      <div class="flex items-center gap-1.5">
        <div class="p-1 rounded bg-green-500/10 text-green-600">
          <CheckCircle class="w-3 h-3" />
        </div>
        <span class="font-medium text-xs">{{ t('chat.taskCompleted') }}</span>
      </div>
      
      <!-- Status Indicator - 简化 -->
      <div class="flex items-center gap-1 text-[10px]" :class="isError ? 'text-destructive' : 'text-green-600'">
        <AlertCircle v-if="isError" class="w-2.5 h-2.5" />
        <Check v-else class="w-2.5 h-2.5" />
        <span>{{ statusText }}</span>
      </div>
    </div>

    <!-- Content Section - 更紧凑 -->
    <div class="px-2.5 py-2 space-y-2">
      <!-- Result Content -->
      <div v-if="resultContent" class="space-y-1.5">
        <!-- Expandable Result with Markdown -->
        <div 
          class="bg-muted/30 rounded border border-border/50 overflow-hidden transition-all duration-300"
          :class="isExpanded ? 'max-h-none' : 'max-h-[300px]'"
        >
          <div class="p-2.5 overflow-y-auto custom-scrollbar" :class="!isExpanded ? 'max-h-[300px]' : ''">
            <MarkdownRenderer :content="resultContent" class="text-xs" />
          </div>
          
          <!-- Gradient overlay when collapsed -->
          <div 
            v-if="!isExpanded" 
            class="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-background to-transparent pointer-events-none"
          ></div>
        </div>
        
        <!-- Expand hint -->
        <div v-if="!isExpanded && contentTooLong" class="text-center">
          <button 
            class="text-[10px] text-muted-foreground hover:text-foreground flex items-center gap-0.5 mx-auto transition-colors"
            @click="isExpanded = true"
          >
            <ChevronDown class="w-3 h-3" />
            {{ t('chat.showMore') }}
          </button>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="isError && errorMessage" class="text-destructive text-xs bg-destructive/5 p-2.5 rounded border border-destructive/20">
        <div class="flex items-start gap-1.5">
          <AlertCircle class="w-3 h-3 mt-0.5 flex-shrink-0" />
          <div>
            <p class="font-medium">{{ t('chat.executionFailed') }}</p>
            <p class="mt-0.5 opacity-90">{{ errorMessage }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CheckCircle, Check, AlertCircle, ChevronDown } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import MarkdownRenderer from '../MarkdownRenderer.vue'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [Object, String],
    default: null
  },
  isLatest: {
    type: Boolean,
    default: false
  },
  openWorkbench: {
    type: Function,
    default: null
  }
})

const emit = defineEmits(['click'])

const { t } = useLanguage()

// Toggle states
const isExpanded = ref(false)

const args = computed(() => {
  try {
    if (typeof props.toolCall.function.arguments === 'string') {
      return JSON.parse(props.toolCall.function.arguments)
    }
    return props.toolCall.function.arguments
  } catch (e) {
    console.error('Failed to parse arguments:', e)
    return {}
  }
})

const finishStatus = computed(() => {
  return args.value.status || ''
})

const resultContent = computed(() => {
  // 优先从参数中获取 result
  const resultFromArgs = args.value.result
  if (resultFromArgs) {
    return typeof resultFromArgs === 'string' ? resultFromArgs : JSON.stringify(resultFromArgs, null, 2)
  }
  
  // 否则从 toolResult 中获取
  if (!props.toolResult) return null
  
  if (typeof props.toolResult === 'string') {
    return props.toolResult
  }
  
  // 尝试获取 content 或 message
  const content = props.toolResult.content || props.toolResult.message
  if (content) {
    return typeof content === 'string' ? content : JSON.stringify(content, null, 2)
  }
  
  // 返回整个对象的字符串表示
  return JSON.stringify(props.toolResult, null, 2)
})

const contentTooLong = computed(() => {
  return resultContent.value && resultContent.value.length > 800
})

const isError = computed(() => {
  if (finishStatus.value === 'failed' || finishStatus.value === 'error') return true
  if (props.toolResult?.status === 'error' || props.toolResult?.is_error) return true
  return false
})

const errorMessage = computed(() => {
  if (!isError.value) return ''
  
  // 尝试从各种可能的字段获取错误信息
  if (props.toolResult?.content) {
    return typeof props.toolResult.content === 'string' 
      ? props.toolResult.content 
      : JSON.stringify(props.toolResult.content)
  }
  
  if (props.toolResult?.message) {
    return props.toolResult.message
  }
  
  if (typeof props.toolResult === 'string') {
    return props.toolResult
  }
  
  return t('error.unknown')
})

const statusText = computed(() => {
  if (isError.value) return t('status.failed')
  return t('status.completed')
})

const handleClick = () => {
  // 触发点击事件，让父组件打开工作台
  emit('click', props.toolCall, props.toolResult)
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.3);
  border-radius: 2px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.5);
}

/* Ensure markdown content is properly styled */
:deep(.markdown-body) {
  font-size: 0.75rem;
  line-height: 1.5;
}

:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3),
:deep(.markdown-body h4) {
  margin-top: 0.75em;
  margin-bottom: 0.375em;
}

:deep(.markdown-body table) {
  margin: 0.75em 0;
}

:deep(.markdown-body pre) {
  margin: 0.75em 0;
}
</style>
