<script setup>
import { computed, ref } from 'vue'
import SchemaField from './SchemaField.vue'
import PluginConfig from './PluginConfig.vue'
import { labels, resolveSchema } from '../config-schema.js'
const props = defineProps({ modelValue: String, schema: Object, resources: Object, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const active = ref('metadata'), mode = ref('form')
const sections = ['metadata', 'entrypoint', 'agents', 'models', 'runtime', 'policies', 'flows', 'credentials', 'plugins', 'interfaces', 'tests', 'environments', 'files']
const bundle = computed(() => { try { return JSON.parse(props.modelValue) } catch { return null } })
const root = computed(() => {
  const schema = JSON.parse(JSON.stringify(props.schema?.bundle_schema || {}))
  const defs = schema.$defs || {}
  for (const name of ['AgentBudgets', 'BudgetConfig']) {
    const steps = defs[name]?.properties?.max_steps
    if (steps?.anyOf) steps.anyOf[0].maximum = 10000
  }
  const route = defs.ModelRoute?.properties
  if (route) {
    route.provider = { type: 'string', const: 'server' }
    for (const key of ['base_url', 'credential', 'plugin', 'capability_profile']) delete route[key]
    route.model = { type: 'string', 'x-option-labels': Object.fromEntries([['default', '默认模型'], ...(props.resources?.models || []).map(item => [item.id, item.model])]), enum: [...new Set(['default', ...(props.resources?.models || []).map(item => item.id), ...Object.values(bundle.value?.manifest?.models || {}).map(item => item.model)])] }
  }
  const agent = defs.AgentDefinition?.properties
  if (agent) {
    agent.mode['x-option-labels'] = { simple: '简单', fibre: 'Fibre', team: '团队' }
    for (const field of ['models', 'delegation_model_bindings']) {
      const current = Object.values(bundle.value?.manifest?.agents || {}).flatMap(item => Object.values(item[field] || {}))
      const routes = [...new Set([...Object.keys(bundle.value?.manifest?.models || {}), ...current])]
      if (routes.length) agent[field].additionalProperties = { type: 'string', enum: routes }
      delete agent[field].patternProperties
    }
    for (const [field, choices] of [['tools', props.resources?.tools?.map(item => item.name)], ['skills', props.resources?.skills?.map(item => item.name)], ['subagents', Object.keys(bundle.value?.manifest?.agents || {})]]) {
      const existing = Object.values(bundle.value?.manifest?.agents || {}).flatMap(item => item[field] || [])
      const values = [...new Set([...(choices || []), ...existing])]
      if (values.length && agent[field]) agent[field].items = { type: 'string', enum: values }
    }
  }
  return schema
})
const manifestSchema = computed(() => resolveSchema(root.value.properties?.manifest, root.value))
const value = computed(() => active.value === 'files' ? bundle.value?.files : bundle.value?.manifest?.[active.value])
const fieldSchema = computed(() => active.value === 'files' ? root.value.properties?.files : manifestSchema.value.properties?.[active.value])
function updatePlugins(value) {
  if (!bundle.value || props.disabled) return
  const next = structuredClone(bundle.value)
  next.manifest.runtime = { ...(next.manifest.runtime || {}), capabilities: value }
  emit('update:modelValue', JSON.stringify(next, null, 2))
}
function update(value) {
  if (!bundle.value || props.disabled) return
  const next = structuredClone(bundle.value)
  if (active.value === 'files') next.files = value
  else next.manifest[active.value] = value
  emit('update:modelValue', JSON.stringify(next, null, 2))
}
</script>
<template>
  <div class="package-editor">
    <div class="row" role="group" aria-label="编辑模式"><button class="btn" :class="{ ghost: mode !== 'form' }" type="button" @click="mode = 'form'">可视化配置</button><button class="btn" :class="{ ghost: mode !== 'source' }" type="button" @click="mode = 'source'">完整定义</button></div>
    <template v-if="mode === 'form' && bundle && root.properties">
      <nav class="config-tabs" aria-label="Package 配置分区"><button v-for="section in sections" :key="section" class="btn" :class="{ ghost: active !== section }" type="button" @click="active = section">{{ labels[section] }}</button></nav>
      <div class="glass-config"><PluginConfig v-if="active === 'runtime'" :model-value="bundle.manifest.runtime?.capabilities || {}" :disabled="disabled" @update:model-value="updatePlugins" /><SchemaField :key="active" :label="labels[active]" :model-value="value" :schema="fieldSchema || {}" :root="root" :disabled="disabled" @update:model-value="update" /></div>
    </template>
    <p v-else-if="mode === 'form' && !bundle" class="error" role="alert">完整定义不是有效 JSON，请在完整定义中修正。</p>
    <label v-else class="field"><span>完整包定义</span><textarea class="mono" aria-label="完整包定义" :value="modelValue" :disabled="disabled" rows="22" spellcheck="false" @input="emit('update:modelValue', $event.target.value)" /></label>
  </div>
</template>
