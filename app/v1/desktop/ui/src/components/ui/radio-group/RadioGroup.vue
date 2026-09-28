<script setup>
import { RadioGroupRoot, RadioGroupItem } from 'radix-vue'
import { cn } from '@/utils/cn'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  class: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <RadioGroupRoot
    :class="cn('grid gap-2', props.class)"
    :model-value="props.modelValue"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <slot />
  </RadioGroupRoot>
</template>
