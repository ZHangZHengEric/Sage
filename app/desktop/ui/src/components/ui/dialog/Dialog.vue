<script setup>
import { DialogRoot, DialogTrigger } from 'radix-vue'

const props = defineProps({
  open: { type: Boolean, default: undefined },
  defaultOpen: { type: Boolean, default: undefined },
  modal: { type: Boolean, default: true },
})

const emit = defineEmits(['update:open'])
</script>

<template>
  <DialogRoot v-bind="props" @update:open="emit('update:open', $event)">
    <slot />
  </DialogRoot>
</template>
