<template>
  <div class="tool-call-item text-foreground/90 w-fit mb-2 flex items-center group cursor-pointer" 
    :class="[imageUrl ? 'max-w-[530px]' : 'max-w-[320px]']"
    @click="handleClick">
    <div class="relative flex items-center justify-between py-2 px-3 rounded-xl bg-muted/30 hover:bg-muted/50 transition-all border border-transparent hover:border-border/40">
      
      <div class="flex items-center gap-3 flex-1 min-w-0">
        <!-- Status Icon -->
        <div class="flex-none flex items-center justify-center w-6 h-6 rounded-full" :class="isCompleted ? 'bg-green-500/10 text-green-500' : 'bg-blue-500/10 text-blue-500'">
           <Check v-if="isCompleted" class="w-3.5 h-3.5" />
           <Loader2 v-else class="w-3.5 h-3.5 animate-spin" />
        </div>

        <div class="flex flex-col min-w-0 gap-0.5 justify-center">
           <span class="text-sm font-medium truncate text-muted-foreground">
             {{ isCompleted ? t('toolCall.completed') : t('toolCall.executing') + '...' }}
           </span>
        </div>
      </div>

      <div class="flex items-center gap-2 pl-4">
         <ChevronRight class="h-4 w-4 text-muted-foreground/70 group-hover:text-foreground transition-colors" />
      </div>
    </div>
    
    <span class="text-[10px] text-muted-foreground ml-2 opacity-0 transition-opacity duration-200 group-hover:opacity-100 whitespace-nowrap">
      {{ t('common.viewDetails') }}
    </span>

    <!-- Markdown Image Preview -->
    <div v-if="imageUrl" class="mt-2 rounded-xl overflow-hidden border border-border/50 bg-background/50">
      <img :src="imageUrl" alt="Tool Generated Image" class="w-full h-auto object-contain max-w-[512px]" loading="lazy" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ChevronRight, Check, Loader2 } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: [Object, String, Array],
    default: null
  }
})

const emit = defineEmits(['click'])

const { t } = useLanguage()

const isCompleted = computed(() => !!props.toolResult)

const imageUrl = computed(() => {
  if (!props.toolResult) return null
  
  let content = ''
  if (typeof props.toolResult === 'string') {
    content = props.toolResult
  } else if (props.toolResult.content && typeof props.toolResult.content === 'string') {
    content = props.toolResult.content
  } else {
    return null
  }

  // Match markdown image syntax ![alt](url)
  const match = content.match(/!\[.*?\]\((.*?)\)/)
  if (match && match[1]) {
    return match[1]
  }
  return null
})

const handleClick = () => {
  emit('click', props.toolCall, props.toolResult)
}
</script>
