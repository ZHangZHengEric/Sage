<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import SchemaField from './SchemaField.vue'
const props = defineProps({ modelValue: { type: Object, default: () => ({}) }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const catalog = ref(null), error = ref('')
const labels = { 'context.summarizer': '会话摘要', 'context.reducer': '上下文压缩', 'context.token-estimator': 'Token 估算', 'context.unit-compactor': '工具结果压缩', 'agent.continuation-policy': '任务继续判定', 'tool.selection-policy': '工具选择', 'skill.loading': '技能加载', 'memory.recall-query': '记忆查询' }
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
      <label class="field"><span>{{ labels[capability] || capability }} <span class="tag">{{ modelValue[capability] ? '显式配置' : '默认' }}</span></span>
        <select :value="modelValue[capability]?.plugin || ''" :disabled="disabled" @change="update(capability, $event.target.value)">
          <option value="">默认 · {{ catalog.defaults[capability] }}</option>
          <option v-if="modelValue[capability] && !options(capability).some(item => item.id === modelValue[capability].plugin)" :value="modelValue[capability].plugin">{{ modelValue[capability].plugin }}</option>
          <option v-for="plugin in options(capability)" :key="plugin.id" :value="plugin.id">{{ plugin.name }} · {{ plugin.id }}</option>
        </select>
      </label>
      <SchemaField v-if="Object.keys(definition(capability)?.schema?.properties || {}).length" :schema="definition(capability).schema" :root="definition(capability).schema" :model-value="parameters(capability)" label="参数" :disabled="disabled" @update:model-value="configure(capability, $event)" />
    </section>
  </div>
</template>
<style scoped>
.plugin-panel { background: color-mix(in srgb, var(--card) 90%, transparent); backdrop-filter: blur(14px); min-width: 0; }
.plugin-panel select { width: 100%; }
</style>
