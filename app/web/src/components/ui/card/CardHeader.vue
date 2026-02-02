<script setup>
import { cn } from '@/utils/cn'

const props = defineProps({
  class: {
    type: String,
    default: '',
  },
})
</script>

<template>
  <div
    :class="cn('flex flex-col space-y-1.5 p-6', props.class)"
  >
    <slot />
  </div>
</template>
