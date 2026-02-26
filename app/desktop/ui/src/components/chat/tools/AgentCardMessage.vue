<template>
  <div class="agent-card-message w-full max-w-[600px] mb-2 rounded-xl border bg-card/50 overflow-hidden transition-all hover:border-border/80">
    <!-- Header Section -->
    <div class="flex items-center justify-between p-3 border-b bg-muted/20">
      <div class="flex items-center gap-2">
        <div class="p-1.5 rounded-lg bg-primary/10 text-primary">
          <Bot class="w-4 h-4" />
        </div>
        <span class="font-medium text-sm">{{ t('chat.agentSpawned') }}</span>
      </div>
      
      <!-- Status Indicator -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
          :class="[
            isError ? 'bg-destructive/10 text-destructive' : 
            isCompleted ? 'bg-green-500/10 text-green-600' : 
            'bg-blue-500/10 text-blue-600'
          ]">
          <AlertCircle v-if="isError" class="w-3 h-3" />
          <Check v-else-if="isCompleted" class="w-3 h-3" />
          <Loader2 v-else class="w-3 h-3 animate-spin" />
          <span>{{ statusText }}</span>
        </div>
      </div>
    </div>

    <!-- Content Section -->
    <div class="p-4 space-y-4">
      <!-- Basic Info -->
      <div class="grid grid-cols-[100px_1fr] gap-2 text-sm">
        <div class="text-muted-foreground font-medium flex items-center gap-1">
          <User class="w-3.5 h-3.5" />
          {{ t('chat.agentName') }}
        </div>
        <div class="font-semibold">{{ args.agent_name || '-' }}</div>
        
        <div class="text-muted-foreground font-medium flex items-center gap-1">
          <Info class="w-3.5 h-3.5" />
          {{ t('chat.agentDescription') }}
        </div>
        <div class="text-foreground/80 leading-relaxed">{{ args.description || '-' }}</div>
      </div>

      <!-- System Prompt Collapsible -->
      <Collapsible v-model:open="isOpen" class=" bg-muted/10">
        <CollapsibleTrigger class="flex items-center justify-between w-full p-3 text-sm font-medium hover:bg-muted/20 transition-colors rounded-t-lg">
          <div class="flex items-center gap-2 text-muted-foreground">
            <FileText class="w-3.5 h-3.5" />
            {{ t('chat.agentSystemPrompt') }}
          </div>
          <div class="p-1 rounded-md hover:bg-muted/30 transition-colors">
            <ChevronDown class="w-4 h-4 transition-transform duration-200" :class="{ 'rotate-180': isOpen }" />
          </div>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div class="p-3 pt-0 border-t border-border/50">
            <div class="mt-3 max-h-[300px] overflow-y-auto custom-scrollbar bg-background/50 rounded-md p-3 text-xs leading-relaxed text-muted-foreground">
              <MarkdownRenderer :content="args.system_prompt || ''" />
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>
  
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Bot, User, Info, FileText, ChevronDown, Check, Loader2, AlertCircle } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
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
  }
})

const { t } = useLanguage()
const isOpen = ref(false)

const args = computed(() => {
  try {
    if (typeof props.toolCall.function.arguments === 'string') {
        return JSON.parse(props.toolCall.function.arguments)
    }
    return props.toolCall.function.arguments
  } catch (e) {
    console.error('Failed to parse agent arguments', e)
    return {}
  }
})

const isCompleted = computed(() => !!props.toolResult)

const isError = computed(() => {
  if (!props.toolResult) return false
  if (typeof props.toolResult === 'object' && (props.toolResult.is_error || props.toolResult.status === 'error')) {
    return true
  }
  if (typeof props.toolResult === 'string' && props.toolResult.toLowerCase().startsWith('error:')) {
    return true
  }
  return false
})

const statusText = computed(() => {
  if (isError.value) return t('common.fail')
  if (isCompleted.value) return t('common.success')
  return t('common.creating')
})

const resultMessage = computed(() => {
  if (!props.toolResult) return ''
  if (typeof props.toolResult === 'string') return props.toolResult
  return props.toolResult.content || ''
})

</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.3);
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.5);
}
</style>
