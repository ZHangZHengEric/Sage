<script setup>
import { computed, useId } from 'vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import { modelCapabilities, modelHelp, modelFieldHelp, modelFieldPlaceholder } from '../model-presentation.js'
const props = defineProps({ modelValue: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const id = useId()
const request = computed(() => props.modelValue.request || {})
const limits = computed(() => props.modelValue.limits || {})
const numbers = [
  { group: 'request', key: 'max_output_tokens', help: 'request_max_output_tokens', label: '单次输出预算', min: 1, step: 1 },
  { group: 'limits', key: 'context_window', help: 'context_window', label: '上下文窗口', min: 1, step: 1 },
  { group: 'limits', key: 'max_output_tokens', help: 'max_output_tokens', label: '模型输出上限', min: 1, step: 1 },
  { group: 'request', key: 'temperature', help: 'temperature', label: 'Temperature', step: 'any' },
  { group: 'request', key: 'top_p', help: 'top_p', label: 'Top P', min: 0, max: 1, step: 'any' },
]
const levels = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
function update(group, key, value) {
  emit('update:modelValue', { ...props.modelValue, capability_profile: null, [group]: { ...(props.modelValue[group] || {}), [key]: value } })
}
function number(event) { return event.target.value === '' ? null : Number(event.target.value) }
</script>
<template>
  <section class="model-section">
    <div class="model-section-title"><AppIcon name="settings" /><h3>生成偏好</h3></div>
    <div class="config-grid">
      <div v-for="field in numbers" :key="field.help" class="field">
        <div class="model-field-label"><label :for="`${id}-${field.help}`">{{ field.label }}</label><FieldHelp :label="field.label" :text="modelFieldHelp(field.help, modelValue)" /></div>
        <input :id="`${id}-${field.help}`" type="number" :min="field.min" :max="field.max" :step="field.step" :placeholder="modelFieldPlaceholder(field.help, modelValue)" :value="(field.group === 'request' ? request : limits)[field.key]" :disabled="disabled" @input="update(field.group, field.key, number($event))" />
      </div>
      <div class="field"><div class="model-field-label"><label :for="`${id}-reasoning`">推理强度</label><FieldHelp label="推理强度" :text="modelHelp.reasoning_effort" /></div><select :id="`${id}-reasoning`" :value="request.reasoning_effort || ''" :disabled="disabled" @change="update('request', 'reasoning_effort', $event.target.value || null)"><option value="">自动（系统默认）</option><option v-for="level in levels" :key="level">{{ level }}</option><option v-if="request.reasoning_effort && !levels.includes(request.reasoning_effort)">{{ request.reasoning_effort }}</option></select></div>
    </div>
  </section>
  <section class="model-section">
    <div class="model-section-title"><AppIcon name="model" /><h3>模型能力</h3></div>
    <div v-for="[key, label] in modelCapabilities" :key="key" class="model-switch-row"><div class="model-field-label"><span :id="`${id}-${key}-label`">{{ label }}</span><FieldHelp :label="label" :text="modelHelp[key]" /></div><button class="model-switch" type="button" role="switch" :aria-labelledby="`${id}-${key}-label`" :aria-checked="modelValue.capabilities?.[key] ?? key === 'tool_calling'" :disabled="disabled" @click="update('capabilities', key, !(modelValue.capabilities?.[key] ?? key === 'tool_calling'))"></button></div>
  </section>
</template>
