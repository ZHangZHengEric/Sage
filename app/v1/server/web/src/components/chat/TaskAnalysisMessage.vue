<template>
  <Collapsible
    v-model:open="isOpen"
    class="task-analysis-message mb-1"
  >
    <CollapsibleTrigger class="w-full">
      <div class="flex items-center justify-start px-2 py-1.5 cursor-pointer select-none transition-all group">
        <div class="header-content flex items-center gap-1.5 flex-1">
          <span class="status-icon flex items-center justify-center" :class="{ 'text-green-500': isCompleted, 'text-blue-500': !isCompleted }">
            <Check v-if="isCompleted" class="w-3.5 h-3.5" />
            <Loader2 v-else class="w-3.5 h-3.5 animate-spin" />
          </span>
          <span class="header-text text-sm font-medium text-foreground">{{ t('chat.taskAnalysisTitle') }}</span>
          <div class="expand-icon text-muted-foreground transition-transform duration-200" >
            <ChevronRight v-if="!isOpen" class="w-3.5 h-3.5" />
            <ChevronDown v-else class="w-3.5 h-3.5" />
          </div>
          <span class="text-[10px] opacity-70 font-normal text-muted-foreground/60 ml-1.5" v-if="timestamp">{{ formatTime(timestamp) }}</span>
          <span class="click-hint text-sm text-muted-foreground ml-1.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100" v-if="!isOpen">{{ t('chat.clickToViewDetails') }}</span>
        </div>
      </div>
    </CollapsibleTrigger>
    <CollapsibleContent class="analysis-content text-sm leading-6 text-muted-foreground pl-7">
      <div class="py-1.5 pr-3">
        <MarkdownRenderer :content="content" />
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Check, Loader2, ChevronRight, ChevronDown } from 'lucide-vue-next'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import MarkdownRenderer from './MarkdownRenderer.vue'
import { useLanguage } from '@/utils/i18n'

const props = defineProps({
  content: {
    type: String,
    required: true
  },
  timestamp: {
    type: [Number, String],
    default: null
  },
  isStreaming: {
    type: Boolean,
    default: false
  }
})

const { t } = useLanguage()

const formatTime = (timestamp) => {
  if (!timestamp) return ''

  let dateVal = timestamp
  const num = Number(timestamp)

  // 如果是数字且看起来像秒级时间戳（小于100亿，对应年份2286年之前）
  // Python后端常返回秒级浮点数时间戳，如 1769963248.061118
  if (!isNaN(num)) {
    if (num < 10000000000) {
      dateVal = num * 1000
    } else {
      dateVal = num
    }
  }

  const date = new Date(dateVal)
  // 检查日期是否有效
  if (isNaN(date.getTime())) return ''

  const now = new Date()
  const isToday = date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear()

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  if (isToday) {
    return `${hours}:${minutes}:${seconds}`
  } else {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
  }
}

const isOpen = ref(false)

const isCompleted = computed(() => !props.isStreaming)
</script>
