<script setup>
import { Label as LabelPrimitive } from 'radix-vue'
import { cva } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const labelVariants = cva(
  'text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
)

const props = defineProps({
  class: {
    type: String,
    default: '',
  },
  as: {
    type: String,
    default: 'label',
  },
  asChild: {
    type: Boolean,
    default: false,
  }
})
</script>

<template>
  <LabelPrimitive
    v-bind="props"
    :class="cn(labelVariants(), props.class)"
  >
    <slot />
  </LabelPrimitive>
</template>
