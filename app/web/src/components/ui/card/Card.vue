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
    :class="cn('rounded-lg border bg-card text-card-foreground shadow-sm', props.class)"
  >
    <slot />
  </div>
</template>
