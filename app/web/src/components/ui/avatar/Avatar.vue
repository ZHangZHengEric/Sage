<script setup>
import { AvatarRoot } from 'radix-vue'
import { cn } from '@/lib/utils'
import { cva } from 'class-variance-authority'

const avatarVariant = cva(
  'relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full'
)

const props = defineProps({
  class: { type: String, default: '' },
  size: { type: String, default: 'default' },
  shape: { type: String, default: 'circle' },
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined }
})
</script>

<template>
  <AvatarRoot
    v-bind="props"
    :class="cn(avatarVariant({ size: props.size, shape: props.shape }), props.class)"
  >
    <slot />
  </AvatarRoot>
</template>
