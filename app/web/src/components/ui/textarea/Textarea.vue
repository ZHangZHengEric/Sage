<script setup>
import { useVModel } from '@vueuse/core'
import { cn } from '@/utils/cn'

const props = defineProps({
  class: { type: String, default: '' },
  defaultValue: { type: [String, Number], default: undefined },
  modelValue: { type: [String, Number], default: undefined },
})

const emit = defineEmits(['update:modelValue'])

const modelValue = useVModel(props, 'modelValue', emit, {
  passive: true,
  defaultValue: props.defaultValue,
})
</script>

<template>
  <textarea
    v-model="modelValue"
    :class="cn('flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', props.class)"
  />
</template>
