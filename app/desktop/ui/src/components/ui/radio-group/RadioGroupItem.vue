<script setup>
import { RadioGroupItem, RadioGroupIndicator } from 'radix-vue'
import { cn } from '@/utils/cn'

const props = defineProps({
  value: {
    type: String,
    required: true
  },
  class: {
    type: String,
    default: ''
  }
})
</script>

<template>
  <RadioGroupItem
    :value="props.value"
    :class="cn(
      'aspect-square h-4 w-4 rounded-full border border-primary text-primary ring-offset-background focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
      props.class
    )"
  >
    <RadioGroupIndicator
      class="flex items-center justify-center"
    >
      <div class="h-2.5 w-2.5 rounded-full bg-current" />
    </RadioGroupIndicator>
  </RadioGroupItem>
</template>
