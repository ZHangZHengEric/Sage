<script setup>
import { computed, ref } from 'vue'
import { labels, chooseSchema, initialValue } from '../config-schema.js'
import FieldHelp from './FieldHelp.vue'
const props = defineProps({ modelValue: null, schema: { type: Object, default: () => ({}) }, root: { type: Object, default: () => ({}) }, label: String, help: String, disabled: Boolean, depth: { type: Number, default: 0 } })
const emit = defineEmits(['update:modelValue'])
const key = ref(''), keyError = ref('')
const definition = computed(() => chooseSchema(props.schema, props.modelValue, props.root))
const object = computed(() => definition.value.type === 'object' || definition.value.properties || (props.modelValue && typeof props.modelValue === 'object' && !Array.isArray(props.modelValue)))
const array = computed(() => definition.value.type === 'array' || Array.isArray(props.modelValue))
const entries = computed(() => Object.entries(definition.value.properties || {}))
const memberSchema = computed(() => Object.values(definition.value.patternProperties || {})[0] || (typeof definition.value.additionalProperties === 'object' ? definition.value.additionalProperties : {}))
const dynamic = computed(() => !definition.value.properties && definition.value.additionalProperties !== false)
function update(value) { if (!props.disabled) emit('update:modelValue', value) }
function child(name, value) { const next = { ...(props.modelValue || {}) }; if (value === undefined) delete next[name]; else next[name] = value; update(next) }
function add() {
  const name = key.value.trim()
  if (!name || Object.hasOwn(props.modelValue || {}, name) || ['__proto__', 'constructor', 'prototype'].includes(name)) { keyError.value = '请输入未使用的名称'; return }
  child(name, initialValue(memberSchema.value, props.root)); key.value = ''; keyError.value = ''
}
function item(index, value) { const next = [...(props.modelValue || [])]; next[index] = value; update(next) }
function numeric(event) { update(event.target.value === '' ? null : Number(event.target.value)) }
</script>
<template>
  <div class="schema-field">
    <div v-if="help" class="schema-label-help"><span>{{ label }}</span><FieldHelp :label="label" :text="help" /></div>
    <select v-if="!definition.type && !definition.properties && !definition.enum && !definition.const" class="value-kind" aria-label="值类型" :disabled="disabled" :value="Array.isArray(modelValue) ? 'array' : modelValue === null ? 'null' : typeof modelValue" @change="update(({string: '', number: 0, boolean: false, object: {}, array: [], null: null})[$event.target.value])"><option value="string">文本</option><option value="number">数值</option><option value="boolean">开关</option><option value="object">对象</option><option value="array">列表</option><option value="null">空值</option></select>
    <template v-if="object">
      <details :open="depth < 2" class="schema-group"><summary>{{ label }}</summary>
        <div class="schema-body">
          <template v-for="[name, field] in entries" :key="name">
            <div class="schema-property">
              <SchemaField v-if="modelValue?.[name] !== undefined && modelValue?.[name] !== null" :model-value="modelValue[name]" :schema="field" :root="root" :label="labels[name] || name" :depth="depth + 1" :disabled="disabled" @update:model-value="child(name, $event)" />
              <button v-else class="btn ghost" type="button" :disabled="disabled" @click="child(name, initialValue(field, root))">添加{{ labels[name] || name }}</button>
              <button v-if="modelValue?.[name] != null && !definition.required?.includes(name)" class="icon-button" type="button" :disabled="disabled" :aria-label="`重置${labels[name] || name}`" @click="child(name, undefined)">×</button>
            </div>
          </template>
          <template v-if="dynamic">
            <div v-for="(value, name) in modelValue || {}" :key="name" class="schema-property">
              <SchemaField :model-value="value" :schema="memberSchema" :root="root" :label="name" :depth="depth + 1" :disabled="disabled" @update:model-value="child(name, $event)" />
              <button class="icon-button" type="button" :disabled="disabled" :aria-label="`删除${name}`" @click="child(name, undefined)">×</button>
            </div>
            <div v-if="!disabled" class="row"><input v-model="key" :aria-label="`${label}新条目名称`" @keydown.enter.prevent="add" /><button class="btn ghost" type="button" @click="add">添加</button></div><p v-if="keyError" class="error" role="alert">{{ keyError }}</p>
          </template>
        </div>
      </details>
    </template>
    <details v-else-if="array" :open="depth < 2" class="schema-group"><summary>{{ label }} · {{ modelValue?.length || 0 }}</summary><div class="schema-body">
      <div v-for="(value, index) in modelValue || []" :key="index" class="schema-property"><SchemaField :model-value="value" :schema="definition.items || {}" :root="root" :label="`${label} ${index + 1}`" :depth="depth + 1" :disabled="disabled" @update:model-value="item(index, $event)" /><button class="icon-button" type="button" :disabled="disabled" :aria-label="`删除${label} ${index + 1}`" @click="update(modelValue.filter((_, i) => i !== index))">×</button></div>
      <button class="btn ghost" type="button" :disabled="disabled" @click="update([...(modelValue || []), initialValue(definition.items, root)])">添加{{ label }}</button>
    </div></details>
    <label v-else-if="definition.enum" class="field"><span :class="{ 'sr-only': help }">{{ label }}</span><select :value="modelValue" :disabled="disabled" @change="update($event.target.value)"><option v-for="option in definition.enum" :key="option" :value="option">{{ definition['x-option-labels']?.[option] || option }}</option></select></label>
    <label v-else-if="definition.type === 'boolean' || typeof modelValue === 'boolean'" class="config-check"><input type="checkbox" :checked="modelValue" :disabled="disabled" @change="update($event.target.checked)" /><span :class="{ 'sr-only': help }">{{ label }}</span></label>
    <label v-else-if="['integer', 'number'].includes(definition.type) || typeof modelValue === 'number'" class="field"><span :class="{ 'sr-only': help }">{{ label }}</span><input type="number" :value="modelValue" :min="definition.minimum ?? (definition.exclusiveMinimum != null ? definition.exclusiveMinimum + 1 : undefined)" :max="definition.maximum" :step="definition.type === 'integer' ? 1 : 'any'" :disabled="disabled" @input="numeric" /></label>
    <label v-else class="field"><span :class="{ 'sr-only': help }">{{ label }}</span><textarea v-if="['提示词内容', '系统提示词'].includes(label) || String(modelValue || '').includes('\n')" :value="modelValue" :disabled="disabled" rows="5" @input="update($event.target.value)" /><input v-else :value="modelValue" :disabled="disabled || definition.const !== undefined" @input="update($event.target.value)" /></label>
  </div>
</template>
