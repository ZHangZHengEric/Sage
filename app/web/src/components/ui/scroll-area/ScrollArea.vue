<script setup>
import { ScrollAreaRoot, ScrollAreaViewport, ScrollAreaCorner } from 'radix-vue'
import ScrollBar from './ScrollBar.vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  class: { type: String, default: '' },
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined },
  type: { type: String, default: undefined },
  dir: { type: String, default: undefined },
  scrollHideDelay: { type: Number, default: undefined }
})
</script>

<template>
  <ScrollAreaRoot
    v-bind="props"
    :class="cn('relative overflow-hidden', props.class)"
  >
    <ScrollAreaViewport class="h-full w-full rounded-[inherit]">
      <slot />
    </ScrollAreaViewport>
    <ScrollBar />
    <ScrollAreaCorner />
  </ScrollAreaRoot>
</template>
