<script setup>
import { ScrollAreaScrollbar, ScrollAreaThumb } from 'radix-vue'
import { cn } from '@/utils/cn'

const props = defineProps({
  orientation: { type: String, default: 'vertical' },
  class: { type: String, default: '' },
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined },
  forceMount: { type: Boolean, default: undefined }
})
</script>

<template>
  <ScrollAreaScrollbar
    v-bind="props"
    :class="
      cn(
        'flex touch-none select-none transition-colors',
        orientation === 'vertical' &&
          'h-full w-2.5 border-l border-l-transparent p-[1px]',
        orientation === 'horizontal' &&
          'h-2.5 flex-col border-t border-t-transparent p-[1px]',
        props.class
      )
    "
  >
    <ScrollAreaThumb class="relative flex-1 rounded-full bg-border" />
  </ScrollAreaScrollbar>
</template>
