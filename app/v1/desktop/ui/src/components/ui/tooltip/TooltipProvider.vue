<script setup>
import { TooltipProvider } from 'radix-vue'

const props = defineProps({
  delayDuration: { type: Number, default: 700 },
  skipDelayDuration: { type: Number, default: 300 },
  disableHoverableContent: { type: Boolean, default: false },
})
</script>

<template>
  <TooltipProvider v-bind="props">
    <slot />
  </TooltipProvider>
</template>
