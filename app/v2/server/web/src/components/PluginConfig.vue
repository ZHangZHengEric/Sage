<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { api } from '../api.js'
import SchemaField from './SchemaField.vue'
import CapabilityCanvas from './CapabilityCanvas.vue'
import AppIcon from './AppIcon.vue'
import { displayValue, pluginName } from '../plugin-presentation.js'
import { labels } from '../config-schema.js'
import { capabilityNodes, effectivePlugin, pluginExplanation, selectionChanged } from '../capability-presentation.js'
const props = defineProps({ modelValue: { type: Object, default: () => ({}) }, savedValue: { type: Object, default: null }, modelLabel: String, disabled: Boolean, catalogData: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue'])
const catalog = ref(null), error = ref(''), loading = ref(false), active = ref('tool.selection-policy'), inspector = ref(null)
const radioName = useId()
let disposed = false
const nodes = computed(() => capabilityNodes(catalog.value, props.modelLabel).map(node => ({ ...node,
  choice: node.id === 'model.provider' ? props.modelLabel : pluginName(effective(node.id).definition || effective(node.id).id),
  available: node.id === 'model.provider' || effective(node.id).available,
  custom: Boolean(props.modelValue[node.id]), changed: changed(node.id),
})))
const currentNode = computed(() => nodes.value.find(node => node.id === active.value))
const current = computed(() => effective(active.value))
const parameterSchema = computed(() => {
  const schema = current.value.definition?.schema || {}
  const hidden = new Set(current.value.id === 'sage.context.reducer.persistent-summary' ? ['max_summary_source_tokens'] : [])
  if (active.value === 'tool.selection-policy' && current.value.id !== 'sage.tool-selection.llm') hidden.add('model_timeout_seconds')
  return { ...schema, properties: Object.fromEntries(Object.entries(schema.properties || {}).filter(([key]) => !hidden.has(key))) }
})
const options = computed(() => catalog.value?.plugins?.filter(plugin => plugin.capabilities.includes(active.value)) || [])
const explanation = computed(() => pluginExplanation(current.value.definition || current.value.id, current.value.config))
const links = computed(() => {
  const result = []
  if (effective('context.reducer').id === 'sage.context.reducer.persistent-summary') result.push(['context.reducer', 'context.summarizer'])
  for (const [capability, ids] of [
    ['tool.selection-policy', ['sage.tool-selection.llm']],
    ['context.summarizer', ['sage.context.summarizer.model']],
    ['agent.continuation-policy', ['sage.agent.continuation.llm-judge', 'sage.agent.continuation.hybrid']],
    ['memory.recall-query', ['sage.memory.recall-query.llm']],
  ]) if (ids.includes(effective(capability).id)) result.push([capability, 'model.provider'])
  return result
})
const changes = computed(() => {
  if (!changed(active.value)) return []
  const before = effectivePlugin(catalog.value, props.savedValue, active.value), after = current.value
  const rows = []
  if (before.id !== after.id) rows.push({ label: '方案', before: pluginName(before.definition || before.id), after: pluginName(after.definition || after.id) })
  if (Boolean(props.savedValue?.[active.value]) !== Boolean(props.modelValue[active.value])) rows.push({ label: '配置来源', before: props.savedValue?.[active.value] ? '自定义' : 'Server 默认', after: props.modelValue[active.value] ? '自定义' : 'Server 默认' })
  for (const key of new Set([...Object.keys(before.config), ...Object.keys(after.config)])) if (selectionChanged(before.config[key], after.config[key])) rows.push({ label: labels[key] || key, before: displayValue(before.config[key]), after: displayValue(after.config[key]) })
  return rows
})
function effective(capability) { return effectivePlugin(catalog.value, props.modelValue, capability) }
function changed(capability) { return props.savedValue !== null && selectionChanged(props.modelValue[capability], props.savedValue[capability]) }
function update(capability, plugin) {
  if (props.disabled || !catalog.value?.configurable?.includes(capability)) return
  const next = { ...props.modelValue }
  if (!plugin) delete next[capability]
  else {
    const option = catalog.value.plugins.find(item => item.id === plugin && item.capabilities.includes(capability))
    if (!option || option.available === false || next[capability]?.plugin === plugin) return
    next[capability] = { ...(next[capability] || {}), plugin, config: {} }
  }
  emit('update:modelValue', next)
}
function configure(capability, config) {
  if (props.disabled || !catalog.value?.configurable?.includes(capability) || !effective(capability).available) return
  emit('update:modelValue', { ...props.modelValue, [capability]: { ...(props.modelValue[capability] || {}), plugin: effective(capability).id, config } })
}
async function load() {
  loading.value = true; error.value = ''
  try { const result = props.catalogData || await api.listPlugins(); if (!disposed) catalog.value = result }
  catch (e) { if (!disposed) error.value = e.message }
  finally { if (!disposed) loading.value = false }
}
watch(nodes, value => { if (catalog.value && !value.some(node => node.id === active.value)) active.value = value[0]?.id || '' })
watch(active, async () => { await nextTick(); inspector.value?.scrollTo?.({ top: 0 }) })
onMounted(load)
onUnmounted(() => { disposed = true })
</script>
<template>
  <div class="plugin-config">
    <div v-if="error" class="catalog-state"><p class="error" role="alert">{{ error }}</p><button class="btn ghost" type="button" :disabled="loading" @click="load">重新加载能力</button></div>
    <p v-else-if="loading || !catalog" class="catalog-state" role="status">正在加载可配置能力…</p>
    <p v-else-if="!nodes.length" class="catalog-state">当前 Server 没有可配置的智能体能力。</p>
    <div v-else class="capability-workbench">
      <CapabilityCanvas :nodes="nodes" :links="links" :active="active" @select="active = $event" />
      <aside ref="inspector" class="capability-inspector" :aria-label="`${currentNode?.name || '能力'}配置`">
        <template v-if="active === 'model.provider'"><header class="inspector-head"><h2>模型配置</h2></header><slot name="model"><p>{{ modelLabel }}</p></slot></template>
        <template v-else-if="currentNode">
          <header class="inspector-head"><h2>{{ currentNode.name }}</h2><span class="tag">{{ options.length }} 个可选方案</span></header>
          <div class="selection-source"><span>{{ modelValue[active] ? '智能体自定义' : '跟随 Server 默认' }}</span><button type="button" :disabled="disabled || !modelValue[active]" @click="update(active, '')">恢复默认</button></div>
          <p v-if="!current.available" class="unavailable-warning" role="alert">当前实现未注册或不可用，请选择可用方案或恢复默认。</p>
          <div role="group" :aria-label="`${currentNode.name}可选方案`" class="plugin-options">
            <label v-for="plugin in options" :key="`${active}:${plugin.id}`" class="plugin-option" :class="{ selected: current.id === plugin.id, unavailable: plugin.available === false }">
              <input type="radio" :name="`${radioName}-${active}`" :value="plugin.id" :checked="current.id === plugin.id" :disabled="disabled || plugin.available === false" @change="update(active, plugin.id)" />
              <span class="option-body"><span class="option-heading"><span class="option-label"><strong>{{ pluginName(plugin) }}</strong><code class="plugin-code">{{ plugin.id }}</code></span><small>{{ plugin.available === false ? '不可用' : current.id === plugin.id ? '当前选择' : catalog.defaults?.[active] === plugin.id ? 'Server 默认' : '' }}</small></span><span class="option-description">{{ pluginExplanation(plugin).description }}</span></span>
            </label>
          </div>
          <div class="effective-selection"><span>当前配置方案</span><strong>{{ pluginName(current.definition || current.id) }}</strong></div>
          <section class="plugin-effects" aria-live="polite"><h3><AppIcon name="skill" />选择后的影响</h3><ul><li v-for="effect in explanation.effects" :key="effect">{{ effect }}</li></ul><p>配置推演 · 实际效果需试运行验证</p></section>
          <section v-if="Object.keys(parameterSchema.properties).length" :key="`${active}:${current.id}`" class="plugin-parameters"><SchemaField :schema="parameterSchema" :root="current.definition.schema" :model-value="current.config" label="参数" :disabled="disabled || !current.available" @update:model-value="configure(active, $event)" /></section>
          <section v-if="changes.length" class="selection-changes"><h3>本次变更 · 未保存</h3><dl><div v-for="change in changes" :key="change.label"><dt>{{ change.label }}</dt><dd><span>{{ change.before }}</span><span aria-label="变更为"> → </span><strong>{{ change.after }}</strong></dd></div></dl></section>
          <p class="save-note">{{ disabled ? '当前为只读配置。' : '修改后请保存配置，用于后续新运行。' }}</p>
        </template>
      </aside>
    </div>
  </div>
</template>
<style scoped>
.plugin-config { container-type: inline-size; min-width: 0; }
.capability-workbench { display: grid; grid-template-columns: minmax(0, 1fr) 350px; height: clamp(650px, calc(100dvh - 190px), 1000px); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--card); }
.capability-inspector { overflow: auto; min-width: 0; padding: 20px; border-left: 1px solid var(--border); }
.inspector-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-bottom: 16px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }.inspector-head h2 { margin: 0; font-size: 17px; }.inspector-head .tag { font-size: 10px; margin: 0; }
.selection-source { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; font-size: 11px; color: var(--muted-foreground); }.selection-source button { background: none; border: 0; color: inherit; font-size: inherit; padding: 3px 0 3px 8px; }.selection-source button:disabled { opacity: .5; cursor: default; }
.plugin-options { display: grid; gap: 9px; }.plugin-option { display: flex; align-items: flex-start; gap: 9px; margin: 0; padding: 12px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; background: var(--card); transition: border-color 120ms ease-out, background 120ms ease-out; }
.plugin-option.selected { border-color: var(--capability-accent); box-shadow: inset 0 0 0 1px var(--capability-accent); background: color-mix(in srgb, var(--capability-soft) 50%, var(--card)); }.plugin-option.unavailable { opacity: .65; cursor: default; }.plugin-option:focus-within { outline: 2px solid var(--capability-accent); outline-offset: 2px; }
.plugin-option input { margin: 4px 0 0; accent-color: var(--capability-accent); flex-shrink: 0; }.option-body { display: block; min-width: 0; flex: 1; }.option-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.option-heading strong { font-size: 12px; font-weight: 550; overflow-wrap: anywhere; }.option-heading small { font-size: 10px; color: var(--capability-accent); white-space: nowrap; }.option-label { display: block; flex: 1; min-width: 0; }.plugin-code { margin-left: 8px; color: var(--muted-foreground); font-size: 11px; font-weight: 400; overflow-wrap: anywhere; }.option-heading { align-items: baseline; }
.option-description { display: block; margin-top: 5px; color: var(--muted-foreground); font-size: 11px; line-height: 1.8; }
.effective-selection { margin-top: 16px; display: grid; gap: 4px; font-size: 11px; color: var(--muted-foreground); }.effective-selection strong { font-size: 12px; color: var(--foreground); font-weight: 500; overflow-wrap: anywhere; }
.plugin-parameters { margin-top: 16px; font-size: 12px; }.plugin-parameters :deep(.schema-body) { padding: 10px 0 0; }.plugin-parameters :deep(.field) { margin: 0; }.plugin-parameters :deep(input), .plugin-parameters :deep(select) { width: 100%; min-width: 0; font-size: 12px; }.plugin-parameters :deep(.schema-property) { align-items: start; }.plugin-parameters :deep(.schema-group) { margin: 0; padding: 0; border: 0; background: transparent; }
.plugin-effects { background: var(--capability-soft); border: 1px solid color-mix(in srgb, var(--capability-accent) 18%, var(--border)); border-radius: 8px; padding: 14px; margin-top: 18px; color: var(--foreground); }.plugin-effects h3 { display: flex; align-items: center; gap: 7px; margin: 0 0 10px; font-size: 12px; }.plugin-effects .app-icon { width: 15px; height: 15px; }.plugin-effects ul { padding-left: 16px; margin: 0; }.plugin-effects li { font-size: 11px; line-height: 1.9; margin: 6px 0; }.plugin-effects p { padding-top: 9px; margin: 10px 0 0; border-top: 1px solid color-mix(in srgb, var(--capability-accent) 14%, transparent); font-size: 10px; color: var(--muted-foreground); }
.selection-changes { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }.selection-changes h3 { font-size: 11px; font-weight: 500; color: var(--muted-foreground); margin: 0 0 8px; }.selection-changes dl { margin: 0; font-size: 11px; }.selection-changes dl > div { margin-top: 8px; }.selection-changes dt { color: var(--muted-foreground); }.selection-changes dd { margin: 2px 0 0; overflow-wrap: anywhere; }.selection-changes dd > span:first-child { color: var(--muted-foreground); }.selection-changes strong { color: var(--capability-accent); font-weight: 500; }
.save-note { margin: 16px 0 0; font-size: 10px; color: var(--muted-foreground); }.unavailable-warning { font-size: 12px; color: var(--destructive); margin: 12px 0; }.catalog-state { padding: 20px; font-size: 13px; }
@container (max-width: 850px) { .capability-workbench { grid-template-columns: minmax(0, 1fr); height: auto; }.capability-workbench :deep(.capability-canvas) { height: 580px; }.capability-inspector { border-left: 0; border-top: 1px solid var(--border); max-height: none; } }
@media (prefers-reduced-motion: reduce) { .plugin-option { transition: none; } }
</style>
