<template>
  <WebAnyToolToolEditor
    :tool="tool"
    :mode="mode"
    :loading="loading"
    @submit="emit('submit', $event)"
    @cancel="emit('cancel')"
  />
</template>

<script setup>
import WebAnyToolToolEditor from '../../../../server/web/src/components/AnyToolToolEditor.vue'

defineProps({
  tool: {
    type: Object,
    default: null
  },
  mode: {
    type: String,
    default: 'create'
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['submit', 'cancel'])
</script>
