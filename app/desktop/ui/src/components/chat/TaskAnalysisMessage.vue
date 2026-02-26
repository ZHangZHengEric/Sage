<template>
  <Collapsible
    v-model:open="isOpen"
    class="task-analysis-message mb-2"
  >
    <CollapsibleTrigger class="w-full">
      <div class="flex items-center justify-start p-3 cursor-pointer select-none transition-all  group">
        <div class="header-content flex items-center gap-2 flex-1">
          <span class="status-icon flex items-center justify-center" :class="{ 'text-green-500': isCompleted, 'text-blue-500': !isCompleted }">
            <Check v-if="isCompleted" class="w-4 h-4" />
            <Loader2 v-else class="w-4 h-4 animate-spin" />
          </span>
          <span class="header-text text-sm font-medium text-foreground">{{ isCompleted ? '任务分析完成' : '任务分析中...' }}</span>
          <div class="expand-icon text-muted-foreground transition-transform duration-200" >
            <ChevronRight v-if="!isOpen" class="w-4 h-4" />
            <ChevronDown v-else class="w-4 h-4" />
          </div>
          <span class="click-hint text-xs text-muted-foreground ml-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100" v-if="!isOpen">点击查看详情</span>
        </div>
      </div>
    </CollapsibleTrigger>
    <CollapsibleContent class="analysis-content text-sm text-muted-foreground pl-9">
      <div class="py-2 pr-4">
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

const props = defineProps({
  content: {
    type: String,
    required: true
  },
  isStreaming: {
    type: Boolean,
    default: false
  }
})

const isOpen = ref(false)

const isCompleted = computed(() => !props.isStreaming)
</script>
