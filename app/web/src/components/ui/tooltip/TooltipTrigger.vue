<script setup>
import { TooltipTrigger } from 'radix-vue'

const props = defineProps({
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined },
})
</script>

<template>
  <TooltipTrigger v-bind="props">
    <slot />
  </TooltipTrigger>
</template>
