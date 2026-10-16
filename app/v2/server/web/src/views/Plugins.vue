<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { isAdmin } from '../auth.js'
import { labels } from '../config-schema.js'
import SchemaField from '../components/SchemaField.vue'
import { componentGroups, pluginName, scopeNames, parameterDefaults, displayValue } from '../plugin-presentation.js'
const catalog = ref(null), server = ref(null), error = ref(''), query = ref(''), active = ref(''), content = ref(null), navigation = ref(null)
const preview = ref({})
const editing = ref(''), draft = ref(null), saving = ref(false), saveError = ref(''), message = ref('')
const editOptions = computed(() => catalog.value?.plugins.filter(p => p.capabilities.includes(editing.value)) || [])
const editPlugin = computed(() => editOptions.value.find(p => p.id === draft.value?.plugin))
const deploymentName = computed(() => pluginName(server.value?.defaults?.[editing.value]?.plugin))
function startEdit(group) {
  editing.value = group.id
  draft.value = server.value.saved[group.id] ? JSON.parse(JSON.stringify(server.value.saved[group.id])) : null
  saveError.value = ''; message.value = ''
}
function choosePlugin(id) {
  if (!id) { draft.value = null; return }
  const plugin = editOptions.value.find(p => p.id === id)
  const config = parameterDefaults(plugin)
  if (plugin?.schema?.properties?.root && config.root === undefined) config.root = `${server.value.storage_root}/${editing.value}`
  draft.value = { plugin: id, config }
}
async function saveServer() {
  saving.value = true; saveError.value = ''
  try {
    server.value = await api.saveServerPlugins({ revision: server.value.revision, changes: { [editing.value]: draft.value } })
    editing.value = ''
    message.value = server.value.pending.length ? '已保存，重启 Server 后生效' : '已保存，与当前运行配置一致'
  } catch (e) { saveError.value = e.message } finally { saving.value = false }
}
async function reloadServer() {
  saving.value = true
  try { server.value = await api.serverPlugins(); startEdit({ id: editing.value }) }
  catch (e) { saveError.value = e.message } finally { saving.value = false }
}
function savedName(group) { const selection = server.value?.saved?.[group.id] || server.value?.defaults?.[group.id]; return selection ? pluginName(selection.plugin) : '部署默认' }
const groups = computed(() => componentGroups(catalog.value, server.value?.providers).filter(group => group.plugins.length !== 1).filter(group => !query.value || `${group.name} ${group.id} ${group.plugins.map(p => `${pluginName(p)} ${p.name} ${p.id}`).join(' ')}`.toLowerCase().includes(query.value.toLowerCase())))
function bindings(group) { return server.value?.providers.filter(item => item.capability === group.id) || [] }
function currentIds(group) { const rows = bindings(group); return rows.length ? [...new Set(rows.map(item => item.plugin_id).filter(Boolean))] : [catalog.value?.defaults[group.id]].filter(Boolean) }
function currentNames(group) { return currentIds(group).map(id => pluginName(group.plugins.find(p => p.id === id) || id)).join('、') || bindings(group).map(item => item.implementation).filter(Boolean).join('、') || '未指定' }
function inspecting(group) { return group.plugins.find(p => p.id === (preview.value[group.id] || currentIds(group)[0])) }
function parameterRows(group) {
  const plugin = inspecting(group)
  if (!plugin) return []
  const selection = server.value?.selections?.[group.id]
  const live = selection?.plugin === plugin.id ? selection.config : {}
  return Object.entries(plugin?.schema?.properties || {}).map(([key]) => ({ key, label: labels[key] || key, value: displayValue(({ ...parameterDefaults(plugin), ...live })[key]) }))
}
function jump(id) { const body = content.value, target = body?.querySelector(`[data-component="${id}"]`); if (!body || !target) return; body.scrollTop += target.getBoundingClientRect().top - body.getBoundingClientRect().top; active.value = id }
function trackSection() { if (!content.value) return; const top = content.value.getBoundingClientRect().top; for (const group of groups.value) if (content.value.querySelector(`[data-component="${group.id}"]`)?.getBoundingClientRect().top <= top + 110) active.value = group.id }
watch(active, async id => {
  await nextTick()
  const nav = navigation.value, button = nav?.querySelector(`[data-nav="${id}"]`)
  if (!nav || !button) return
  const area = nav.getBoundingClientRect(), item = button.getBoundingClientRect()
  if (item.left < area.left) nav.scrollLeft += item.left - area.left
  else if (item.right > area.right) nav.scrollLeft += item.right - area.right
  if (item.top < area.top) nav.scrollTop += item.top - area.top
  else if (item.bottom > area.bottom) nav.scrollTop += item.bottom - area.bottom
})
watch(query, async () => { await nextTick(); active.value = groups.value[0]?.id || ''; if (content.value) content.value.scrollTop = 0 })
onMounted(async () => { try { [catalog.value, server.value] = await Promise.all([api.listPlugins(), isAdmin() ? api.serverPlugins() : null]); active.value = groups.value[0]?.id || '' } catch (e) { error.value = e.message } })
</script>
<template>
  <section class="plugins-page">
    <header class="page-head"><h1>插件</h1><input v-model="query" type="search" aria-label="搜索组件或插件" placeholder="搜索组件或插件" /></header>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="server?.pending?.length" class="pending-config" role="status">{{ server.pending.length }} 项 Server 配置待重启生效</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-else-if="!catalog" role="status">加载中…</p>
    <div v-else-if="groups.length" class="component-layout">
      <nav ref="navigation" class="component-nav panel" aria-label="插件组件"><button v-for="group in groups" :key="group.id" :data-nav="group.id" :class="{ active: active === group.id }" :aria-current="active === group.id ? 'true' : undefined" @click="jump(group.id)">{{ group.name }}</button></nav>
      <div ref="content" class="component-content" @scroll="trackSection">
        <article v-for="group in groups" :key="group.id" :data-component="group.id" class="panel component-card">
          <div class="component-head"><h2>{{ group.name }}</h2><div class="row"><button v-if="server?.configurable?.includes(group.id)" class="btn ghost" :disabled="!!editing" @click="startEdit(group)">配置 Server</button><router-link v-if="catalog.configurable?.includes(group.id)" class="btn ghost" to="/agents">配置智能体</router-link><router-link v-else-if="group.id === 'model.provider'" class="btn ghost" to="/models">模型配置</router-link></div></div>
          <div class="current-choice"><span class="status-dot"></span><span>Server 默认：<strong>{{ currentNames(group) }}</strong></span></div>
          <div v-if="server?.pending?.includes(group.id)" class="pending-config">已保存：{{ savedName(group) }} · 待重启</div>
          <form v-if="editing === group.id" class="server-editor stack" @submit.prevent="saveServer">
            <label class="field"><span>Server 默认插件</span><select :value="draft?.plugin || ''" :disabled="saving" @change="choosePlugin($event.target.value)"><option value="">跟随部署默认 · {{ deploymentName }}</option><option v-for="plugin in editOptions" :key="plugin.id" :value="plugin.id" :disabled="plugin.available === false">{{ pluginName(plugin) }}{{ plugin.available === false ? '（不可用）' : '' }}</option></select></label>
            <SchemaField v-if="editPlugin && Object.keys(editPlugin.schema?.properties || {}).length" :schema="editPlugin.schema" :root="editPlugin.schema" :model-value="draft.config" label="插件参数" :disabled="saving" @update:model-value="draft.config = $event" />
            <p v-if="saveError" class="error" role="alert">{{ saveError }}</p>
            <div class="row"><button class="btn" :disabled="saving" type="submit">{{ saving ? '保存中…' : '保存 Server 配置' }}</button><button v-if="saveError" class="btn ghost" :disabled="saving" type="button" @click="reloadServer">重新加载配置</button><button class="btn ghost" :disabled="saving" type="button" @click="editing = ''">取消</button></div>
          </form>
          <div class="selected-tags"><span class="tag">{{ catalog.configurable?.includes(group.id) ? '智能体可覆盖' : server?.configurable?.includes(group.id) ? 'Server 可配置' : server ? '部署管理' : 'Server 管理' }}</span><span v-if="currentIds(group).length" class="tag">{{ bindings(group).length ? '正在使用' : '默认选择' }}</span><span v-for="scope in [...new Set(bindings(group).map(b => b.scope))]" :key="scope" class="tag">作用域：{{ scopeNames[scope] || scope }}</span></div>
          <details v-if="group.plugins.length" class="plugin-options"><summary>查看可选实现（{{ group.plugins.length }}）</summary><div class="implementation-list"><button v-for="plugin in group.plugins" :key="plugin.id" class="implementation" :class="{ inspecting: inspecting(group)?.id === plugin.id }" :aria-pressed="inspecting(group)?.id === plugin.id" @click="preview[group.id] = plugin.id"><span>{{ pluginName(plugin) }}</span><span v-if="currentIds(group).includes(plugin.id)" class="implementation-status">当前</span></button></div></details>
          <details v-if="parameterRows(group).length" class="plugin-options"><summary>插件参数 · {{ pluginName(inspecting(group)) }}</summary><dl class="parameter-list"><div v-for="row in parameterRows(group)" :key="row.key"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl></details>
          <details class="plugin-options technical"><summary>技术信息</summary><dl class="parameter-list"><div><dt>组件标识</dt><dd>{{ group.id }}</dd></div><div v-for="plugin in group.plugins" :key="plugin.id"><dt>{{ pluginName(plugin) }}</dt><dd>{{ plugin.id }}</dd></div></dl></details>
        </article>
      </div>
    </div>
    <p v-else-if="catalog" class="empty">没有匹配的组件或插件</p>
  </section>
</template>
<style scoped>
.plugins-page { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.server-editor { padding: 16px; margin: 12px 0; border: 1px solid var(--border); border-radius: 12px; background: var(--muted); }.server-editor select { width: 100%; }.pending-config { color: var(--primary); font-size: 13px; margin: 8px 0 12px; }
.component-layout { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 20px; min-height: 0; flex: 1; }
.component-nav { align-self: start; max-height: 100%; overflow: auto; padding: 8px; display: grid; gap: 3px; }
.component-nav button { padding: 11px 12px; border: 0; background: transparent; color: var(--foreground); border-radius: 8px; text-align: left; cursor: pointer; }
.component-nav button.active { background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); }
.component-nav button:hover { background: var(--muted); }
.component-content { overflow: auto; min-width: 0; padding: 0 8px 24px 0; scroll-padding-top: 4px; }
.component-card { margin-bottom: 14px; background: color-mix(in srgb, var(--card) 90%, transparent); backdrop-filter: blur(14px); }
.component-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.component-head h2 { font-size: 18px; margin: 0; }
.current-choice { display: flex; align-items: center; gap: 9px; margin: 16px 0 12px; flex-wrap: wrap; }.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary); }
.selected-tags { margin-bottom: 16px; }.plugin-options { border-top: 1px solid var(--border); padding: 12px 0; }.plugin-options:last-child { padding-bottom: 0; }.plugin-options summary { cursor: pointer; font-size: 13px; }
.implementation-list { display: grid; gap: 4px; margin-top: 10px; }.implementation { display: flex; align-items: center; gap: 10px; padding: 10px; background: transparent; border: 1px solid transparent; color: var(--foreground); text-align: left; border-radius: 8px; cursor: pointer; }.implementation:hover,.implementation.inspecting { background: var(--muted); }.option-dot { width: 14px; height: 14px; border: 1px solid var(--border); border-radius: 50%; flex-shrink: 0; }.option-dot.selected { border: 4px solid var(--primary); }.implementation-status { margin-left: auto; color: var(--primary); font-size: 12px; }
.parameter-list { margin: 14px 0 0; }.parameter-list > div { display: grid; grid-template-columns: minmax(120px, .9fr) minmax(0, 1.1fr); gap: 16px; padding: 8px 0; font-size: 13px; }.parameter-list dt { color: var(--muted-foreground); }.parameter-list dd { margin: 0; overflow-wrap: anywhere; }.technical dd { font-family: monospace; font-size: 12px; }
@media (max-width: 760px) { .component-layout { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); gap: 12px; }.component-nav { display: flex; overflow-x: auto; }.component-nav button { flex-shrink: 0; }.component-content { padding-right: 0; }.parameter-list > div { grid-template-columns: 1fr; gap: 5px; } }
</style>
