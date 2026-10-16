<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import SchemaField from './SchemaField.vue'
import { componentName, pluginName } from '../plugin-presentation.js'
const props = defineProps({ modelValue: { type: Object, default: () => ({}) }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const catalog = ref(null), error = ref('')

const capabilities = computed(() => catalog.value?.configurable || [])
function options(capability) { return catalog.value.plugins.filter(item => item.capabilities.includes(capability)) }
function selected(capability) { return props.modelValue[capability]?.plugin || catalog.value.defaults[capability] }
function definition(capability) { return catalog.value.plugins.find(item => item.id === selected(capability)) }
function parameters(capability) {
  const fields = definition(capability)?.schema?.properties || {}
  const defaults = Object.fromEntries(Object.entries(fields).filter(([, field]) => field.default !== undefined).map(([key, field]) => [key, field.default]))
  const host = !props.modelValue[capability] ? catalog.value.default_config?.[capability] || {} : {}
  return { ...defaults, ...host, ...(props.modelValue[capability]?.config || {}) }
}
function update(capability, plugin) {
  const next = { ...props.modelValue }
  if (!plugin) delete next[capability]
  else next[capability] = { plugin, config: {} }
  emit('update:modelValue', next)
}
function configure(capability, config) {
  emit('update:modelValue', { ...props.modelValue, [capability]: { ...(props.modelValue[capability] || {}), plugin: selected(capability), config } })
}
onMounted(async () => { try { catalog.value = await api.listPlugins() } catch (e) { error.value = e.message } })
</script>
<template>
  <div class="plugin-config stack">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="!catalog" role="status">加载中…</p>
    <section v-for="capability in capabilities" :key="capability" class="panel plugin-panel">
      <label class="field"><span>{{ componentName(capability) }} <span class="tag">{{ modelValue[capability] ? '自定义' : '跟随默认' }}</span></span>
        <select :value="modelValue[capability]?.plugin || ''" :disabled="disabled" @change="update(capability, $event.target.value)">
          <option value="">默认 · {{ pluginName(catalog.plugins.find(item => item.id === catalog.defaults[capability]) || catalog.defaults[capability]) }}</option>
          <option v-if="modelValue[capability] && !options(capability).some(item => item.id === modelValue[capability].plugin)" :value="modelValue[capability].plugin">{{ modelValue[capability].plugin }}</option>
          <option v-for="plugin in options(capability)" :key="plugin.id" :value="plugin.id">{{ pluginName(plugin) }}</option>
        </select>
      </label>
      <SchemaField v-if="Object.keys(definition(capability)?.schema?.properties || {}).length" :schema="definition(capability).schema" :root="definition(capability).schema" :model-value="parameters(capability)" label="参数" :disabled="disabled" @update:model-value="configure(capability, $event)" />
      <details class="plugin-technical"><summary>技术信息</summary><code>{{ selected(capability) }}</code></details>
    </section>
  </div>
</template>
<style scoped>
.plugin-panel { background: color-mix(in srgb, var(--card) 90%, transparent); backdrop-filter: blur(14px); min-width: 0; }
.plugin-panel select { width: 100%; }
.plugin-technical { margin-top: 12px; font-size: 12px; }.plugin-technical summary { cursor: pointer; }.plugin-technical code { display: block; margin-top: 8px; overflow-wrap: anywhere; }
</style>
