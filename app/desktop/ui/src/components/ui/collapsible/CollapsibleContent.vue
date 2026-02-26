<script setup>
import { CollapsibleContent, useForwardProps } from 'radix-vue'

const props = defineProps({
  forceMount: { type: Boolean, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: null, required: false },
})

const forwardedProps = useForwardProps(props)
</script>

<template>
  <CollapsibleContent v-bind="forwardedProps">
    <slot />
  </CollapsibleContent>
</template>
