<script setup>
import { ref, watch } from 'vue'
import { cn } from '@/utils/cn'

defineOptions({
  inheritAttrs: false,
})

const props = defineProps({
  class: { type: String, default: '' },
  defaultValue: { type: [String, Number], default: undefined },
  modelValue: { type: [String, Number], default: undefined },
})

const emit = defineEmits(['update:modelValue'])

// 使用内部 ref 来管理值，避免 computed setter 干扰中文输入
const innerValue = ref(props.modelValue ?? props.defaultValue ?? '')

// 监听外部值变化
watch(() => props.modelValue, (newVal) => {
  if (newVal !== innerValue.value) {
    innerValue.value = newVal ?? ''
  }
})

const handleInput = (e) => {
  const value = e.target.value
  innerValue.value = value
  emit('update:modelValue', value)
}
</script>

<template>
  <textarea
    :value="innerValue"
    v-bind="$attrs"
    @input="handleInput"
    :class="cn('flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50', props.class)"
  />
</template>
