<script setup>
import SchemaField from './SchemaField.vue'
defineProps({ modelValue: Object, label: String, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
</script>
<template><SchemaField :model-value="modelValue" :label="label" :schema="{ type: 'object', additionalProperties: true }" :disabled="disabled" @update:model-value="emit('update:modelValue', $event)" /></template>
