<script setup>
import { Separator } from 'radix-vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  orientation: { type: String, default: 'horizontal' },
  decorative: { type: Boolean, default: true },
  class: { type: String, default: '' },
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined }
})
</script>

<template>
  <Separator
    v-bind="props"
    :class="
      cn(
        'shrink-0 bg-border',
        orientation === 'horizontal' ? 'h-[1px] w-full' : 'h-full w-[1px]',
        props.class
      )
    "
  />
</template>
