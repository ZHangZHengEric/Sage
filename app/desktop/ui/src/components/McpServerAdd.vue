<template>
  <WebMcpServerAdd
    ref="innerRef"
    :loading="loading"
    :is-edit="isEdit"
    @submit="emit('submit', $event)"
    @cancel="emit('cancel')"
  />
</template>

<script setup>
import { ref } from 'vue'
import WebMcpServerAdd from '../../../../server/web/src/components/McpServerAdd.vue'

const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  },
  isEdit: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['submit', 'cancel'])
const innerRef = ref(null)

const resetForm = () => innerRef.value?.resetForm?.()
const setFormData = (data) => innerRef.value?.setFormData?.(data)
const addTool = () => innerRef.value?.addTool?.()

defineExpose({
  resetForm,
  setFormData,
  addTool
})
</script>
