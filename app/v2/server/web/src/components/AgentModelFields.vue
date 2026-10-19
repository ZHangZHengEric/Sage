<script setup>
import { computed, useId } from 'vue'
import FieldHelp from './FieldHelp.vue'
import { agentHelp } from '../agent-presentation.js'
const props = defineProps({ modelId: String, fastModelId: String, models: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['update:modelId', 'update:fastModelId'])
const id = useId()
const defaultModelLabel = computed(() => props.models.find(model => model.is_default)?.model || '当前用户默认模型')
</script>
<template>
  <div class="field"><div class="agent-model-label"><label :for="`${id}-primary`">主模型</label><FieldHelp label="主模型" :text="agentHelp.model" /></div><select :id="`${id}-primary`" :value="modelId || ''" :disabled="disabled" @change="emit('update:modelId', $event.target.value)"><option value="">{{ defaultModelLabel }}（系统默认）</option><option v-if="modelId && !models.some(model => model.id === modelId)" :value="modelId">{{ modelId }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.model }}</option></select></div>
  <div class="field"><div class="agent-model-label"><label :for="`${id}-fast`">辅助模型</label><FieldHelp label="辅助模型" :text="agentHelp.fast_model" /></div><select :id="`${id}-fast`" :value="fastModelId || ''" :disabled="disabled" @change="emit('update:fastModelId', $event.target.value)"><option value="">跟随主模型（系统默认）</option><option v-if="fastModelId && !models.some(model => model.id === fastModelId)" :value="fastModelId">{{ fastModelId }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.model }}</option></select></div>
</template>
<style scoped>
.agent-model-label { display: flex; align-items: center; gap: 3px; }
</style>
