<script setup>
import { DialogTrigger } from 'radix-vue'

const props = defineProps({
  asChild: { type: Boolean, default: false },
  as: { type: String, default: undefined }
})
</script>

<template>
  <DialogTrigger v-bind="props">
    <slot />
  </DialogTrigger>
</template>
