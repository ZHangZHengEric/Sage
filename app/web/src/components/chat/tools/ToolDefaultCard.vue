<template>
  <div class="tool-call-item bg-secondary/30 text-secondary-foreground border border-border/30 rounded-2xl rounded-tl-sm p-2 shadow-sm overflow-hidden break-words w-fit max-w-[260px] mb-2" @click="handleClick">
    <div class="relative flex items-center justify-between p-2 rounded-xl bg-background border border-border/50 hover:border-primary/30 hover:shadow-md transition-all cursor-pointer group">
      <!-- Status Indicator -->
      <div class="absolute left-0 top-3 bottom-3 w-1 rounded-r-full transition-colors"
           :class="isCompleted ? 'bg-green-500/50' : 'bg-blue-500/50'"></div>

      <div class="flex items-center gap-3 flex-1 min-w-0 pl-3">

        <div class="flex flex-col min-w-0 gap-0.5">
          <span class="font-medium text-sm truncate text-foreground/90 group-hover:text-primary transition-colors">{{ toolName }}</span>
          <span class="text-[10px] text-muted-foreground truncate font-mono opacity-80 flex items-center gap-1">
             <span class="w-1.5 h-1.5 rounded-full" :class="isCompleted ? 'bg-green-500' : 'bg-blue-500 animate-pulse'"></span>
             {{ isCompleted ? t('toolCall.completed') : t('toolCall.executing') }}
          </span>
        </div>
      </div>

      <div class="flex items-center gap-2">
         <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-full" @click.stop="handleClick">
            <ChevronRight class="h-4 w-4" />
         </Button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { ChevronRight } from 'lucide-vue-next'
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

const toolName = computed(() => props.toolCall?.function?.name || 'Unknown Tool')
const isCompleted = computed(() => !!props.toolResult)

const handleClick = () => {
  emit('click', props.toolCall, props.toolResult)
}
</script>
