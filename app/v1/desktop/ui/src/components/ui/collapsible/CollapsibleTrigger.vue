<script setup>
import { CollapsibleTrigger, useForwardProps } from 'radix-vue'

const props = defineProps({
  asChild: { type: Boolean, required: false },
  as: { type: null, required: false },
})

const forwardedProps = useForwardProps(props)
</script>

<template>
  <CollapsibleTrigger v-bind="forwardedProps">
    <slot />
  </CollapsibleTrigger>
</template>
