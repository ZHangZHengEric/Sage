<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { isAdmin } from '../auth.js'
import SchemaField from '../components/SchemaField.vue'
import AppIcon from '../components/AppIcon.vue'
import FieldHelp from '../components/FieldHelp.vue'
import FormDrawer from '../components/FormDrawer.vue'
import { systemCategory, parameterHelp, parameterLabel, policyHelp } from '../system-settings-presentation.js'
import { componentGroups, componentName, pluginName, parameterDefaults, displayValue } from '../plugin-presentation.js'
import { pluginExplanation, selectionChanged } from '../capability-presentation.js'
const pendingOpen = ref(false), loading = ref(true)
const catalog = ref(null), server = ref(null), error = ref(''), active = ref('')
const preview = ref({}), drafts = ref({})
const editing = ref(''), draft = ref(null), saving = ref(false), saveError = ref(''), message = ref('')
const allGroups = computed(() => componentGroups(catalog.value, [
  ...(server.value?.providers || []),
  ...new Set([...(server.value?.configurable || []), ...Object.keys(server.value?.defaults || {}), ...Object.keys(server.value?.saved || {}), ...Object.keys(server.value?.selections || {})]),
].map(item => typeof item === 'string' ? { capability: item } : item)))
const groups = allGroups
const currentGroup = computed(() => allGroups.value.find(group => group.id === active.value))
const editOptions = computed(() => catalog.value?.plugins.filter(p => p.capabilities.includes(editing.value)) || [])
const editPlugin = computed(() => editOptions.value.find(p => p.id === draft.value?.plugin))
const inspected = computed(() => currentGroup.value && inspecting(currentGroup.value))
const inspectedConfig = computed(() => currentGroup.value ? configuration(currentGroup.value) : {})
const explanation = computed(() => pluginExplanation(inspected.value, inspectedConfig.value))
function modificationRestriction(id) {
  if (!server.value) return '仅管理员可修改系统默认配置。'
  if (!server.value.configurable?.includes(id)) return '此项由服务端固定配置，页面不支持修改。'
  const options = allGroups.value.find(group => group.id === id)?.plugins.filter(plugin => plugin.available !== false) || []
  if (!options.length) return '当前没有可用实现，页面不支持修改。'
  const hasParameters = options.some(plugin => Object.values(plugin.schema?.properties || {}).some(field =>
    field.type || field.enum || field.$ref || field.anyOf || field.oneOf || field.allOf))
  if (options.length === 1 && !hasParameters) return '当前只有一种可用实现，且没有可在页面修改的参数。'
  return ''
}
function canConfigure(id) { return !modificationRestriction(id) }
function implementationSelected(plugin) {
  if (!canConfigure(active.value)) return currentIds(currentGroup.value).includes(plugin.id)
  return (editing.value === active.value ? draft.value : server.value.saved?.[active.value])?.plugin === plugin.id
}
function keepDraft() {
  if (editing.value) drafts.value[editing.value] = draft.value === null ? null : JSON.parse(JSON.stringify(draft.value))
}
function startEdit(group) {
  if (saving.value || !canConfigure(group.id)) return
  keepDraft()
  active.value = group.id; editing.value = group.id
  const value = Object.hasOwn(drafts.value, group.id) ? drafts.value[group.id] : server.value.saved?.[group.id] || null
  draft.value = value === null ? null : JSON.parse(JSON.stringify(value))
  saveError.value = ''; message.value = ''
}
function selectNode(id) {
  if (saving.value) return
  keepDraft(); editing.value = ''; active.value = id; saveError.value = ''
  const group = allGroups.value.find(item => item.id === id)
  if (group && canConfigure(id)) startEdit(group)
}
function choosePlugin(id) {
  if (saving.value || !canConfigure(editing.value)) return
  if (!id) { draft.value = null; return }
  const plugin = editOptions.value.find(p => p.id === id)
  if (!plugin || plugin.available === false) return
  const config = parameterDefaults(plugin)
  if (plugin.schema?.properties?.root && config.root === undefined && server.value.storage_root) config.root = `${server.value.storage_root}/${editing.value}`
  draft.value = { plugin: id, config }
}
function selectImplementation(plugin) {
  if (saving.value) return
  if (!canConfigure(active.value)) return
  if (plugin.available === false) return
  if (editing.value !== active.value) startEdit(currentGroup.value)
  if (draft.value?.plugin !== plugin.id) choosePlugin(plugin.id)
}
function resetDefault() {
  if (!canConfigure(active.value) || saving.value) return
  if (editing.value !== active.value) startEdit(currentGroup.value)
  choosePlugin('')
}
function cancelEdit() { delete drafts.value[editing.value]; editing.value = ''; draft.value = null; saveError.value = '' }
async function saveServer() {
  if (!editing.value || !canConfigure(editing.value) || saving.value) return
  saving.value = true; saveError.value = ''
  const id = editing.value
  try {
    server.value = await api.saveServerPlugins({ revision: server.value.revision, changes: { [id]: draft.value } })
    delete drafts.value[id]; delete preview.value[id]; editing.value = ''
    message.value = server.value.pending.length ? '系统默认已保存，重启 Server 后生效' : '系统默认已保存，与当前运行配置一致'
  } catch (e) { saveError.value = e.message } finally { saving.value = false }
}
async function reloadServer() {
  if (saving.value) return
  saving.value = true
  const id = editing.value || active.value
  try { server.value = await api.serverPlugins(); delete drafts.value[id]; editing.value = ''; saving.value = false; startEdit({ id }) }
  catch (e) { saveError.value = e.message } finally { saving.value = false }
}
function savedName(group) { const selection = server.value?.saved?.[group.id] || server.value?.defaults?.[group.id]; return selection ? pluginName(selection.plugin) : '部署默认' }
function bindings(group) { return server.value?.providers?.filter(item => item.capability === group.id) || [] }
function currentIds(group) { const rows = bindings(group); return rows.length ? [...new Set(rows.map(item => item.plugin_id).filter(Boolean))] : [catalog.value?.defaults?.[group.id]].filter(Boolean) }
function currentNames(group) { return currentIds(group).map(id => pluginName(group.plugins.find(p => p.id === id) || id)).join('、') || bindings(group).map(item => item.implementation).filter(Boolean).join('、') || '未指定' }
function inspecting(group) {
  const id = editing.value === group.id ? draft.value?.plugin || server.value?.defaults?.[group.id]?.plugin
    : preview.value[group.id] || server.value?.saved?.[group.id]?.plugin || currentIds(group)[0]
  return group.plugins.find(p => p.id === id) || group.plugins[0]
}
function configuration(group) {
  const plugin = inspecting(group)
  if (!plugin) return {}
  const choices = editing.value === group.id ? [draft.value, server.value?.defaults?.[group.id]] : [server.value?.saved?.[group.id], server.value?.selections?.[group.id], server.value?.defaults?.[group.id]]
  const selected = choices.find(selection => selection?.plugin === plugin.id)
  return { ...parameterDefaults(plugin), ...(selected?.config || {}) }
}
function parameterRows(group) {
  const plugin = inspecting(group), config = configuration(group)
  return Object.keys(plugin?.schema?.properties || {}).map(key => ({ key, label: parameterLabel(key), value: displayValue(config[key]) }))
}
function localDraft(group) { return editing.value === group.id ? draft.value : drafts.value[group.id] }
function dirty(group) {
  return (editing.value === group.id || Object.hasOwn(drafts.value, group.id)) && selectionChanged(localDraft(group), server.value?.saved?.[group.id] || null)
}
const navigationItems = computed(() => groups.value.map(group => ({ ...group, icon: group.id.startsWith('memory') || group.id.startsWith('session-memory') ? 'history' : 'settings',
  choice: dirty(group) ? pluginName(localDraft(group)?.plugin || server.value?.defaults?.[group.id]?.plugin) : canConfigure(group.id) ? savedName(group) : currentNames(group),
  changed: dirty(group), sourceText: !canConfigure(group.id) ? '不可修改' : dirty(group) ? '未保存' : server.value?.pending?.includes(group.id) ? '待重启' : '系统默认',
})))
const categoryGroups = computed(() => {
  const buckets = ['模型、工具与智能体', '记忆与上下文', '执行与资源', '运行基础']
  return buckets.map(name => ({ name, items: navigationItems.value.filter(item => systemCategory(item.id) === name) })).filter(group => group.items.length)
})
const pendingGroups = computed(() => (server.value?.pending || []).map(id => groups.value.find(group => group.id === id) || { id, name: componentName(id), plugins: [] }))
const currentDirty = computed(() => currentGroup.value && dirty(currentGroup.value))
const draftChanges = computed(() => {
  const group = currentGroup.value
  if (!group || !dirty(group)) return []
  const saved = server.value?.saved?.[group.id] || null
  const next = localDraft(group)
  const deployment = server.value?.defaults?.[group.id]
  const beforePlugin = saved?.plugin || deployment?.plugin || catalog.value?.defaults?.[group.id]
  const afterPlugin = next?.plugin || deployment?.plugin || catalog.value?.defaults?.[group.id]
  const changes = []
  if (beforePlugin !== afterPlugin) changes.push({ key: '实现', before: pluginName(beforePlugin), after: pluginName(afterPlugin) })
  else {
    const definition = group.plugins.find(plugin => plugin.id === beforePlugin)
    const before = { ...parameterDefaults(definition), ...((saved || deployment)?.config || {}) }
    const after = configuration(group)
    for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
      if (selectionChanged(before[key], after[key])) changes.push({ key: parameterLabel(key), before: displayValue(before[key]), after: displayValue(after[key]) })
    }
  }
  if (!changes.length) changes.push({ key: '配置来源', before: saved ? '显式覆盖' : '跟随部署默认', after: next ? '显式覆盖' : '跟随部署默认' })
  return changes
})
const parameterFields = computed(() => Object.entries(inspected.value?.schema?.properties || {}))
function configureParameter(key, value) {
  if (saving.value || !canConfigure(active.value) || editing.value !== active.value || !draft.value) return
  const config = { ...configuration(currentGroup.value) }
  if (value === undefined) delete config[key]; else config[key] = value
  draft.value.config = config
}
watch(groups, value => { if (!value.some(group => group.id === active.value)) selectNode(value[0]?.id || '') })
async function load() {
  loading.value = true; error.value = ''
  try {
    const [plugins, settings] = await Promise.all([api.listPlugins(), isAdmin() ? api.serverPlugins() : null])
    catalog.value = plugins; server.value = settings; selectNode(groups.value[0]?.id || '')
  } catch (e) { error.value = e.message } finally { loading.value = false }
}
onMounted(load)
</script>
<template>
  <section class="system-settings plugins-page" aria-label="系统插件">
    <p v-if="message" class="system-message" role="status"><span><AppIcon name="check" />{{ message }}</span><button class="icon-button" type="button" aria-label="关闭提示" @click="message = ''"><AppIcon name="close" /></button></p>
    <div v-if="error" class="system-error" role="alert"><span>{{ error }}</span><button class="btn ghost" type="button" :disabled="loading" @click="load">重新加载</button></div>
    <div v-if="loading" class="system-skeleton" aria-busy="true" aria-label="正在加载系统插件"><i v-for="n in 4" :key="n"></i></div>
    <div v-else-if="groups.length" class="system-workbench">
      <nav class="system-navigation" aria-label="系统插件分类"><div v-for="category in categoryGroups" :key="category.name" class="system-category"><div class="system-category-title">{{ category.name }}</div><button v-for="node in category.items" :key="node.id" type="button" :class="{ active: active === node.id }" :aria-current="active === node.id ? 'true' : undefined" :disabled="saving" @click="selectNode(node.id)"><span class="navigation-title">{{ node.name }}<small :class="{ 'is-dirty': node.changed, 'is-pending': node.sourceText === '待重启' }">{{ ['不可修改', '未保存', '待重启'].includes(node.sourceText) ? node.sourceText : '' }}</small></span><span class="navigation-choice">{{ node.choice }}</span></button></div></nav>
      <article v-if="currentGroup" class="system-inspector" :aria-label="`${currentGroup.name}系统默认配置`">
        <div class="system-inspector-content">
        <header class="inspector-head"><div><AppIcon name="settings" /><h1>{{ currentGroup.name }}</h1></div><span v-if="!canConfigure(active)" class="system-readonly-mark">不可修改</span></header>
        <div v-if="pendingGroups.length" class="system-pending-notice"><span><AppIcon name="clock" />{{ pendingGroups.length }} 项系统默认配置待重启生效</span><button type="button" @click="pendingOpen = true">查看变更</button></div>
        <dl class="configuration-status"><div><dt><i></i>当前运行</dt><dd>{{ currentNames(currentGroup) }}</dd></div><div v-if="server"><dt>已保存默认<FieldHelp label="已保存默认" :text="policyHelp.saved" /></dt><dd>{{ savedName(currentGroup) }}<span v-if="server.pending?.includes(active)" class="system-badge amber">待重启</span><span v-else class="system-badge neutral">与运行一致</span></dd></div></dl>
        <form id="system-plugin-form" class="plugin-configuration" @submit.prevent="saveServer">
          <section class="implementation-section"><div class="system-section-title"><h2>实现选择</h2><span>{{ currentGroup.plugins.length }} 个实现</span></div>
            <div class="implementation-list" role="group" :aria-label="`${currentGroup.name}实现`">
              <button v-if="canConfigure(active)" class="default-option" :class="{ selected: editing === active ? !draft : !server.saved?.[active] }" type="button" :disabled="saving" :aria-pressed="editing === active ? !draft : !server.saved?.[active]" @click="resetDefault"><span class="option-indicator" aria-hidden="true"></span><span class="implementation-copy"><strong>跟随部署默认</strong><code class="plugin-code">{{ server.defaults?.[active]?.plugin }}</code><span class="implementation-description">{{ pluginName(server.defaults?.[active]?.plugin) }}</span></span></button>
              <button v-for="plugin in currentGroup.plugins" :key="plugin.id" type="button" class="implementation" :class="{ selected: implementationSelected(plugin) }" :disabled="saving || !canConfigure(active) || plugin.available === false" :aria-pressed="implementationSelected(plugin)" @click="selectImplementation(plugin)"><span class="option-indicator" aria-hidden="true"></span><span class="implementation-copy"><span class="implementation-heading"><strong>{{ pluginName(plugin) }}</strong><small>{{ plugin.available === false ? '当前不可用' : currentIds(currentGroup).includes(plugin.id) ? '运行中' : implementationSelected(plugin) ? '已选择' : '' }}</small></span><code class="plugin-code">{{ plugin.id }}</code><span class="implementation-description">{{ pluginExplanation(plugin).description }}</span></span></button>
              <div v-if="!currentGroup.plugins.length" class="system-injected"><AppIcon name="lock" /><div><strong>宿主注入</strong><p>{{ currentNames(currentGroup) }}</p></div></div>
            </div>
            <p v-if="!canConfigure(active)" class="management-note"><AppIcon name="lock" />{{ modificationRestriction(active) }}</p>
          </section>
          <div class="configuration-section">
            <section v-if="inspected" class="plugin-effects"><div class="system-section-title"><h2>{{ canConfigure(active) ? '选择后的影响' : '实现说明' }}</h2></div><ul><li v-for="effect in explanation.effects" :key="effect">{{ effect }}</li></ul></section>
            <section v-if="parameterFields.length" class="system-parameters"><h2>配置参数</h2><template v-if="canConfigure(active) && editing === active && draft && editPlugin"><SchemaField v-for="[key, field] in parameterFields" :key="`${active}:${draft.plugin}:${key}`" :schema="field" :root="editPlugin.schema" :model-value="inspectedConfig[key]" :label="parameterLabel(key)" :help="parameterHelp(key, field)" :disabled="saving" @update:model-value="configureParameter(key, $event)" /></template><dl v-else class="system-parameter-values"><div v-for="row in parameterRows(currentGroup)" :key="row.key"><dt>{{ row.label }}<FieldHelp :label="row.label" :text="parameterHelp(row.key, inspected.schema.properties[row.key])" /></dt><dd>{{ row.value }}</dd></div></dl></section>
            <p v-else class="system-no-parameters">{{ currentGroup.plugins.length ? '此实现无页面配置参数' : '此能力由宿主提供，页面仅供查看' }}</p>
            <dl v-if="draftChanges.length" class="system-draft-changes" aria-label="本次配置变更"><div v-for="change in draftChanges" :key="change.key"><dt>{{ change.key }}</dt><dd><span>{{ change.before }}</span><AppIcon name="chevron" /><strong>{{ change.after }}</strong></dd></div></dl>
          </div>
        </form>
        </div>
        <footer class="system-save-footer"><div v-if="canConfigure(active)"><div v-if="saveError" class="system-error" role="alert"><span>{{ saveError }}，草稿已保留。</span><button class="system-reload" type="button" :disabled="saving" @click="reloadServer">丢弃本项草稿并重载</button></div><div class="system-save-row"><span class="system-save-state"><AppIcon :name="currentDirty ? 'settings' : 'check'" />{{ currentDirty ? (editing === active && !draft ? '保存后使用部署默认配置' : '本项有未保存修改') : '本项无未保存修改' }}</span><div class="row"><template v-if="editing === active"><button class="btn ghost" :disabled="saving || !currentDirty" type="button" @click="cancelEdit">撤销修改</button><button class="btn cta" :disabled="saving || !currentDirty" type="submit" form="system-plugin-form">{{ saving ? '保存中…' : '保存系统默认' }}</button></template><button v-else class="btn cta" type="button" @click="startEdit(currentGroup)">配置系统默认</button></div></div></div><span v-else class="system-save-state"><AppIcon name="lock" />此项不可在页面修改</span></footer>
      </article>
    </div>
    <div v-else-if="catalog && !error" class="system-empty"><AppIcon name="settings" /><h2>暂无系统插件</h2></div>
    <FormDrawer v-model="pendingOpen" centered panel-class="system-settings system-pending-dialog" title="待重启的系统默认配置"><section v-for="group in pendingGroups" :key="group.id" class="system-pending-item"><h3>{{ group.name }}</h3><div><span>运行：{{ currentNames(group) }}</span><AppIcon name="chevron" /><span>已保存：{{ savedName(group) }}</span></div></section><p class="system-pending-explanation">保存不会立即改变运行中的实现。新系统默认配置需要重启 Server 后生效。</p><template #footer><div class="system-dialog-footer"><span>{{ pendingGroups.length }} 项待生效</span><button class="btn ghost" type="button" @click="pendingOpen = false">关闭</button></div></template></FormDrawer>
  </section>
</template>
<style src="../system-settings.css"></style>
