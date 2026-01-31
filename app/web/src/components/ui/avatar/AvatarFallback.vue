<script setup>
import { AvatarFallback } from 'radix-vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  delayMs: { type: Number, default: undefined },
  class: { type: String, default: '' },
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined }
})
</script>

<template>
  <AvatarFallback
    v-bind="props"
    :class="cn('flex h-full w-full items-center justify-center rounded-full bg-muted', props.class)"
  >
    <slot />
  </AvatarFallback>
</template>
