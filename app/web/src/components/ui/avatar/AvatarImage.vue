<script setup>
import { AvatarImage } from 'radix-vue'
import { cn } from '@/lib/utils'

const props = defineProps({
  src: { type: String, required: true },
  alt: { type: String, default: '' },
  class: { type: String, default: '' },
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined }
})
</script>

<template>
  <AvatarImage
    v-bind="props"
    :class="cn('aspect-square h-full w-full', props.class)"
  />
</template>
