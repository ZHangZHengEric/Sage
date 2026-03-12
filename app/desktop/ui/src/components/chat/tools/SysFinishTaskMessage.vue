<template>
  <div class="sys-finish-task-message w-full max-w-[800px] mb-2 rounded-xl border bg-card/50 overflow-hidden transition-all hover:border-border/80">
    <!-- Header Section -->
    <div class="flex items-center justify-between p-3 border-b bg-muted/20">
      <div class="flex items-center gap-2">
        <div class="p-1.5 rounded-lg bg-green-500/10 text-green-600">
          <CheckCircle class="w-4 h-4" />
        </div>
        <span class="font-medium text-sm">{{ t('chat.taskCompleted') }}</span>
      </div>
      
      <!-- Status Indicator -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
          :class="[
            isError ? 'bg-destructive/10 text-destructive' : 
            'bg-green-500/10 text-green-600'
          ]">
          <AlertCircle v-if="isError" class="w-3 h-3" />
          <Check v-else class="w-3 h-3" />
          <span>{{ statusText }}</span>
        </div>
      </div>
    </div>

    <!-- Content Section -->
    <div class="p-4 space-y-4">
      <!-- Status Badge -->
      <!-- <div class="flex items-center gap-2">
        <Badge :variant="isError ? 'destructive' : 'default'" class="text-xs">
          {{ statusLabel }}
        </Badge>
        <span v-if="finishStatus" class="text-xs text-muted-foreground">
          {{ finishStatus }}
        </span>
      </div> -->

      <!-- Result Content - Full Markdown Rendering -->
      <div v-if="resultContent" class="space-y-3">
        <div class="flex items-center justify-between">
          <h4 class="text-sm font-medium">{{ t('chat.executionResult') }}</h4>
          <Button 
            variant="ghost" 
            size="sm" 
            class="h-7 text-xs gap-1"
            @click="isExpanded = !isExpanded"
          >
            <Eye v-if="!isExpanded" class="w-3.5 h-3.5" />
            <EyeOff v-else class="w-3.5 h-3.5" />
            {{ isExpanded ? t('chat.collapse') : t('chat.expand') }}
          </Button>
        </div>
        
        <!-- Expandable Result with Markdown -->
        <div 
          class="bg-muted/30 rounded-lg border border-border/50 overflow-hidden transition-all duration-300"
          :class="isExpanded ? 'max-h-none' : 'max-h-[400px]'"
        >
          <div class="p-4 overflow-y-auto custom-scrollbar" :class="!isExpanded ? 'max-h-[400px]' : ''">
            <MarkdownRenderer :content="resultContent" class="text-sm" />
          </div>
          
          <!-- Gradient overlay when collapsed -->
          <div 
            v-if="!isExpanded" 
            class="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent pointer-events-none"
          ></div>
        </div>
        
        <!-- Expand hint -->
        <div v-if="!isExpanded && contentTooLong" class="text-center">
          <Button 
            variant="ghost" 
            size="sm" 
            class="text-xs gap-1"
            @click="isExpanded = true"
          >
            <ChevronDown class="w-3.5 h-3.5" />
            {{ t('chat.showMore') }}
          </Button>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="isError && errorMessage" class="text-destructive text-sm bg-destructive/5 p-4 rounded-lg border border-destructive/20">
        <div class="flex items-start gap-2">
          <AlertCircle class="w-4 h-4 mt-0.5 flex-shrink-0" />
          <div>
            <p class="font-medium">{{ t('chat.executionFailed') }}</p>
            <p class="mt-1 opacity-90">{{ errorMessage }}</p>
          </div>
        </div>
      </div>

      <!-- Raw Data Toggle -->
      <div v-if="hasRawData" class="pt-2 border-t border-border/30">
        <Button 
          variant="ghost" 
          size="sm" 
          class="h-7 text-xs gap-1 text-muted-foreground"
          @click="showRawData = !showRawData"
        >
          <Code class="w-3.5 h-3.5" />
          {{ showRawData ? t('chat.hideRawData') : t('chat.showRawData') }}
        </Button>
        
        <div v-if="showRawData" class="mt-2">
          <JsonDataViewer :data="rawData" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { CheckCircle, Check, AlertCircle, Eye, EyeOff, ChevronDown, Code } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import MarkdownRenderer from '../MarkdownRenderer.vue'
import JsonDataViewer from './JsonDataViewer.vue'

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
  }
})

const { t } = useLanguage()

// Toggle states
const isExpanded = ref(false)
const showRawData = ref(false)

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
  return resultContent.value && resultContent.value.length > 1000
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

const statusLabel = computed(() => {
  if (isError.value) return t('chat.failed')
  return t('chat.success')
})

const rawData = computed(() => {
  return {
    arguments: args.value,
    result: props.toolResult
  }
})

const hasRawData = computed(() => {
  return Object.keys(args.value).length > 0 || props.toolResult
})
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.3);
  border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.5);
}

/* Ensure markdown content is properly styled */
:deep(.markdown-body) {
  font-size: 0.875rem;
  line-height: 1.6;
}

:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3),
:deep(.markdown-body h4) {
  margin-top: 1em;
  margin-bottom: 0.5em;
}

:deep(.markdown-body table) {
  margin: 1em 0;
}

:deep(.markdown-body pre) {
  margin: 1em 0;
}
</style>
