<script setup>
import { cn } from '@/utils/cn'

const props = defineProps({
  class: { type: String, default: '' },
})
</script>

<template>
  <caption :class="cn('mt-4 text-sm text-muted-foreground', props.class)">
    <slot />
  </caption>
</template>
