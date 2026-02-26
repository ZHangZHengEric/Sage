<script setup>
import { SelectGroup } from 'radix-vue'
import { cn } from '@/utils/cn'

const props = defineProps({
  asChild: { type: Boolean, required: false },
  as: { type: null, required: false },
  class: { type: String, default: '' },
})
</script>

<template>
  <SelectGroup :class="cn('p-1', props.class)" v-bind="props">
    <slot />
  </SelectGroup>
</template>
