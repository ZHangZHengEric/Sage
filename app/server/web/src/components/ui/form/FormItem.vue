<script setup>
import { Label } from '@/components/ui/label'
import { cn } from '@/utils/cn'

defineProps({
  label: { type: String, default: '' },
  error: { type: String, default: '' },
  required: { type: Boolean, default: false },
  class: { type: String, default: '' }
})
</script>

<template>
  <div :class="cn('space-y-2', $props.class)">
    <div v-if="label" class="flex items-center gap-1">
      <Label :class="error ? 'text-destructive' : ''">{{ label }}</Label>
      <span v-if="required" class="text-destructive">*</span>
    </div>
    <slot />
    <p v-if="error" class="text-[0.8rem] font-medium text-destructive">
      {{ error }}
    </p>
  </div>
</template>
