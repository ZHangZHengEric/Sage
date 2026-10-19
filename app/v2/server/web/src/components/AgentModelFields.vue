<script setup>
defineProps({ modelId: String, fastModelId: String, models: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['update:modelId', 'update:fastModelId'])
</script>
<template>
  <label class="field"><span>主模型</span><select :value="modelId || ''" :disabled="disabled" @change="emit('update:modelId', $event.target.value)"><option value="">使用默认模型</option><option v-if="modelId && !models.some(model => model.id === modelId)" :value="modelId">{{ modelId }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.model }}</option></select></label>
  <label class="field"><span>辅助模型</span><select :value="fastModelId || ''" :disabled="disabled" @change="emit('update:fastModelId', $event.target.value)"><option value="">跟随主模型</option><option v-if="fastModelId && !models.some(model => model.id === fastModelId)" :value="fastModelId">{{ fastModelId }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.model }}</option></select></label>
</template>
