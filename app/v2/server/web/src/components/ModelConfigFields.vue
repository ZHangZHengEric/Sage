<script setup>
import { computed } from 'vue'
const props = defineProps({ modelValue: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const request = computed(() => props.modelValue.request || {})
const limits = computed(() => props.modelValue.limits || {})
const capabilities = [['multimodal', '多模态'], ['structured_output', '结构化输出'], ['tool_calling', '工具调用'], ['reasoning', '推理'], ['parallel_tool_calls', '并行工具调用']]
function update(group, key, value) {
  emit('update:modelValue', { ...props.modelValue, capability_profile: null, [group]: { ...(props.modelValue[group] || {}), [key]: value } })
}
function number(event) { return event.target.value === '' ? null : Number(event.target.value) }
</script>
<template>
  <div class="config-grid">
    <label class="field"><span>请求输出 Token</span><input type="number" min="1" :value="request.max_output_tokens" :disabled="disabled" @input="update('request', 'max_output_tokens', number($event))" /></label>
    <label class="field"><span>上下文窗口</span><input type="number" min="1" :value="limits.context_window" :disabled="disabled" @input="update('limits', 'context_window', number($event))" /></label>
    <label class="field"><span>模型输出上限</span><input type="number" min="1" :value="limits.max_output_tokens" :disabled="disabled" @input="update('limits', 'max_output_tokens', number($event))" /></label>
    <label class="field"><span>Temperature</span><input type="number" step="any" :value="request.temperature" :disabled="disabled" @input="update('request', 'temperature', number($event))" /></label>
    <label class="field"><span>Top P</span><input type="number" step="any" min="0" max="1" :value="request.top_p" :disabled="disabled" @input="update('request', 'top_p', number($event))" /></label>
    <label class="field"><span>推理强度</span><select :value="request.reasoning_effort || ''" :disabled="disabled" @change="update('request', 'reasoning_effort', $event.target.value || null)"><option value="">自动</option><option v-for="level in ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']" :key="level">{{ level }}</option><option v-if="request.reasoning_effort && !['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].includes(request.reasoning_effort)">{{ request.reasoning_effort }}</option></select></label>
  </div>
  <div class="config-toggles"><label v-for="[key, label] in capabilities" :key="key"><input type="checkbox" :checked="modelValue.capabilities?.[key] ?? key === 'tool_calling'" :disabled="disabled" @change="update('capabilities', key, $event.target.checked)" />{{ label }}</label></div>
</template>
