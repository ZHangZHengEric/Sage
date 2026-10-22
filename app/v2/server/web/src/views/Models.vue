<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { api, isForeign } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import FormDrawer from '../components/FormDrawer.vue'
import FieldHelp from '../components/FieldHelp.vue'
import ModelConfigFields from '../components/ModelConfigFields.vue'
import CapabilityReport from '../components/CapabilityReport.vue'
import JsonObjectField from '../components/JsonObjectField.vue'
import { modelCapabilityLabels, modelHelp, protocols, providerIdentity, probeStatus } from '../model-presentation.js'

const drawerOpen = ref(false), editing = ref(''), viewOnly = ref(false), selectedModel = ref(null)
const models = ref([]), error = ref(''), message = ref(''), loading = ref(true)
const pending = ref(false), probing = ref(false), showKey = ref(false), confirmDelete = ref(false)
const search = ref(''), filter = ref('all')
const busy = computed(() => pending.value || probing.value)
const form = ref(emptyForm())
const identity = computed(() => providerIdentity(form.value))
const filters = [['all', '全部模型'], ['checked', '已探测'], ['default', '默认模型']]
const visibleModels = computed(() => {
  const query = search.value.trim().toLowerCase()
  return models.value.filter(item => {
    if (filter.value === 'checked' && !item.capability_profile?.outcomes?.length) return false
    if (filter.value === 'default' && !item.is_default) return false
    return !query || [item.model, item.base_url, item.protocol, providerIdentity(item).name, item._owner?.username].join(' ').toLowerCase().includes(query)
  }).map(item => ({ ...item, identity: providerIdentity(item), probe: probeStatus(item.capability_profile),
    labels: modelCapabilityLabels(item) }))
})
const defaultBaseUrls = {
  'openai-chat-completions': 'https://api.openai.com/v1',
  'openai-responses': 'https://api.openai.com/v1',
  'anthropic-messages': 'https://api.anthropic.com',
  'gemini-generate-content': 'https://generativelanguage.googleapis.com/v1beta',
  orcarouter: 'https://api.orcarouter.ai/v1',
  cheaperinference: 'https://api.cheaperinference.com/v1',
}
function emptyForm() { return { protocol: 'openai-chat-completions', base_url: 'https://api.openai.com/v1', model: '', api_key: '' } }
function invalidate() { form.value.capability_profile = null }
function updateForm(value) { form.value = value }
function onProtocolChange() {
  invalidate()
  if (!form.value.base_url || Object.values(defaultBaseUrls).includes(form.value.base_url)) form.value.base_url = defaultBaseUrls[form.value.protocol]
}
async function refresh() { models.value = await api.listModels() }
async function load() {
  loading.value = true; error.value = ''
  try { await refresh() } catch (exc) { error.value = exc.message } finally { loading.value = false }
}
async function probe() {
  if (viewOnly.value || isForeign(selectedModel.value) || busy.value) return
  error.value = ''; probing.value = true
  try {
    const profile = await api.probeModel({ ...form.value, ...(editing.value ? { id: editing.value } : {}) })
    const capabilities = { ...(form.value.capabilities || {}) }
    for (const [key, names] of [['multimodal', ['multimodal']], ['structured_output', ['structured_output', 'json_object']], ['tool_calling', ['tool_calling']], ['reasoning', ['reasoning_control']]]) {
      const outcomes = (profile.outcomes || []).filter(item => names.includes(item.name))
      if (outcomes.some(item => item.status === 'supported')) capabilities[key] = true
      else if (outcomes.length === names.length && outcomes.every(item => item.status === 'unsupported')) capabilities[key] = false
    }
    form.value = { ...form.value, capability_profile: profile, capabilities }
  } catch (exc) { error.value = exc.message } finally { probing.value = false }
}
async function save() {
  if (viewOnly.value || isForeign(selectedModel.value) || busy.value) return
  error.value = ''; pending.value = true
  try {
    await api.saveModel({ ...form.value, ...(editing.value ? { id: editing.value } : {}),
      is_default: editing.value ? selectedModel.value.is_default : !models.value.some(item => !isForeign(item)) })
    form.value.api_key = ''; drawerOpen.value = false
    message.value = '模型配置已保存'
    await refresh()
  } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function makeCurrent(item) {
  if (!item || isForeign(item) || busy.value) return
  error.value = ''; message.value = ''; pending.value = true
  try {
    await api.saveModel({ request: item.request, limits: item.limits, capabilities: item.capabilities, capability_profile: item.capability_profile,
      id: item.id, protocol: item.protocol, base_url: item.base_url, model: item.model, api_key: '', is_default: true })
    message.value = `已将 ${item.model} 设为默认模型`
    await refresh()
  } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function remove(item) {
  if (!item || isForeign(item) || item.is_default || busy.value) return
  error.value = ''; pending.value = true
  try {
    await api.deleteModel(item.id)
    drawerOpen.value = false; message.value = '模型已删除'
    await refresh()
  } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
function startNew() {
  if (busy.value || loading.value) return
  editing.value = ''; viewOnly.value = false; selectedModel.value = null
  error.value = ''; message.value = ''; showKey.value = false; confirmDelete.value = false
  form.value = emptyForm(); drawerOpen.value = true
}
async function openModel(item, readonly = true) {
  if (busy.value) return
  error.value = ''; message.value = ''; pending.value = true
  try {
    const detail = await api.getModel(item.id, item._owner)
    editing.value = item.id; selectedModel.value = item
    form.value = { protocol: detail.protocol, base_url: detail.base_url, model: detail.model, api_key: detail.api_key || '', request: detail.request, limits: detail.limits, capabilities: detail.capabilities, capability_profile: detail.capability_profile }
    viewOnly.value = readonly || isForeign(item)
    showKey.value = false; confirmDelete.value = false; drawerOpen.value = true
  } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
watch(drawerOpen, open => { if (!open) { form.value.api_key = ''; showKey.value = false; confirmDelete.value = false } })
onMounted(load)
</script>

<template>
  <section class="model-page" aria-label="模型供应商">
    <PageToolbar aria-label="模型操作"><template v-if="models.length"><div class="model-filters" aria-label="模型筛选"><button v-for="[value, label] in filters" :key="value" type="button" :aria-pressed="filter === value" @click="filter = value">{{ label }}</button></div></template><template #actions><template v-if="models.length"><label class="model-search"><AppIcon name="search" /><input v-model="search" type="search" aria-label="搜索模型或供应商" placeholder="搜索模型或供应商" /></label></template><button class="btn cta" type="button" :disabled="busy || loading" @click="startNew"><AppIcon name="plus" />新增模型</button></template></PageToolbar>
    <div v-if="message" class="model-message" role="status"><span><AppIcon name="check" />{{ message }}</span><button class="icon-button" type="button" aria-label="关闭提示" @click="message = ''"><AppIcon name="close" /></button></div>
    <p v-if="error && !drawerOpen && models.length" class="error model-list-error" role="alert">{{ error }}<button class="btn ghost" type="button" :disabled="busy || loading" @click="load">重新加载</button></p>
    <div v-if="loading" class="model-grid" aria-busy="true" aria-label="正在加载模型"><div v-for="n in 3" :key="n" class="model-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="error && !models.length" class="model-empty" role="alert"><span class="model-empty-icon"><AppIcon name="link" /></span><h2>暂时无法加载模型</h2><p>{{ error }}</p><button class="btn cta" type="button" @click="load">重新加载</button></div>
    <div v-else-if="!models.length" class="model-empty"><span class="model-empty-icon"><AppIcon name="model" /></span><h2>添加你的第一个模型</h2><button class="btn cta" type="button" :disabled="busy" @click="startNew"><AppIcon name="plus" />新增模型</button></div>
    <div v-else-if="!visibleModels.length" class="model-empty"><span class="model-empty-icon"><AppIcon name="search" /></span><h2>没有找到匹配的模型</h2><button class="btn ghost" type="button" @click="search = ''; filter = 'all'">清除筛选</button></div>
    <div v-else class="model-grid">
      <article v-for="item in visibleModels" :key="`${item._owner?.user_id || ''}:${item.id}`" class="model-card" :class="{ 'is-default': item.is_default }">
        <header class="model-card-head"><span class="model-monogram" :data-tone="item.identity.tone" aria-hidden="true">{{ item.identity.monogram }}</span><div class="model-card-name"><div class="model-name-line"><h2>{{ item.model }}</h2><span v-if="item.is_default" class="model-badge">默认</span></div><div class="model-vendor">{{ item.identity.name }}<span v-if="item._owner"> · {{ item._owner.username }}</span></div></div></header>
        <div class="model-card-capabilities"><span v-for="label in item.labels" :key="label" class="model-badge neutral">{{ label }}</span><span v-if="!item.labels.length" class="model-vendor">尚未声明能力</span></div>
        <div class="model-endpoint"><AppIcon name="link" /><span :title="item.base_url">{{ item.base_url }}</span></div>
        <footer class="model-card-footer"><span class="model-probe-status" :data-state="item.probe.state"><i></i>{{ item.probe.label }}</span><div class="model-card-actions"><button class="btn ghost" type="button" :aria-label="`${isForeign(item) ? '查看' : '配置'} ${item.model}`" :disabled="busy" @click="openModel(item, isForeign(item))">{{ isForeign(item) ? '查看' : '配置' }}<AppIcon name="chevron" /></button><button v-if="!isForeign(item) && !item.is_default" class="btn ghost" type="button" :disabled="busy" @click="makeCurrent(item)">设为默认</button></div></footer>
      </article>
      <button class="model-card model-add-card" type="button" :disabled="busy" @click="startNew"><span><AppIcon name="plus" /></span>连接新模型</button>
    </div>

    <FormDrawer v-model="drawerOpen" centered panel-class="model-dialog" :title="viewOnly ? '查看模型配置' : editing ? '模型配置' : '新增模型'" :busy="busy">
      <form v-if="drawerOpen" id="model-config-form" class="model-form" @submit.prevent="save">
        <div class="model-detail-identity"><span class="model-monogram" :data-tone="identity.tone" aria-hidden="true">{{ identity.monogram }}</span><div><h2>{{ form.model || '新模型' }}</h2><span class="model-vendor">{{ identity.name }}</span></div><span v-if="selectedModel?.is_default" class="model-badge">默认模型</span><span v-if="isForeign(selectedModel)" class="model-badge neutral">{{ selectedModel._owner.username }} · 只读</span></div>
        <section class="model-section"><div class="model-section-title"><AppIcon name="link" /><h3>连接设置</h3></div><div class="model-connection-fields">
          <div class="field"><div class="model-field-label"><label for="model-protocol">接口协议</label><FieldHelp label="接口协议" :text="modelHelp.protocol" /></div><select id="model-protocol" v-model="form.protocol" :disabled="viewOnly || busy" @change="onProtocolChange"><option v-for="(label, value) in protocols" :key="value" :value="value">{{ label }}</option><option v-if="!protocols[form.protocol]" :value="form.protocol">{{ form.protocol }}</option></select></div>
          <div class="field"><div class="model-field-label"><label for="model-url">API 地址</label><FieldHelp label="API 地址" :text="modelHelp.base_url" /></div><input id="model-url" v-model="form.base_url" type="url" placeholder="https://api.openai.com/v1" :readonly="viewOnly" :disabled="busy" required @input="invalidate" /></div>
          <div class="field"><div class="model-field-label"><label for="model-name">模型名称</label><FieldHelp label="模型名称" :text="modelHelp.model" /></div><input id="model-name" v-model="form.model" placeholder="填写服务商提供的模型标识" :readonly="viewOnly" :disabled="busy" required @input="invalidate" /></div>
          <div class="field"><div class="model-field-label"><label for="model-key">API Key</label><FieldHelp label="API Key" :text="modelHelp.api_key" /></div><div class="model-key-input"><input id="model-key" v-model="form.api_key" :type="showKey ? 'text' : 'password'" :placeholder="editing ? '留空保留原密钥' : '填写服务商 API Key'" :readonly="viewOnly" :disabled="busy" :required="!editing" autocomplete="off" spellcheck="false" @input="invalidate" /><button class="icon-button" type="button" :aria-label="showKey ? '隐藏密钥' : '显示密钥'" :aria-pressed="showKey" @click="showKey = !showKey"><AppIcon name="eye" /></button></div></div>
        </div></section>
        <ModelConfigFields :model-value="form" :disabled="viewOnly || busy" @update:model-value="updateForm" />
        <details class="model-section model-advanced"><summary><h3>高级配置</h3><AppIcon name="chevron" /></summary><div class="model-extra"><div class="model-field-label"><span>扩展请求参数</span><FieldHelp label="扩展请求参数" :text="modelHelp.extra" /></div><JsonObjectField label="扩展请求参数" :model-value="form.request?.extra || {}" :disabled="viewOnly || busy" @update:model-value="form = { ...form, capability_profile: null, request: { ...form.request, extra: $event } }" /></div></details>
        <section class="model-section"><div class="model-probe-heading"><div class="model-section-title"><AppIcon name="check" /><h3>能力探测</h3><FieldHelp label="能力探测" :text="modelHelp.probe" /></div><button v-if="!viewOnly" class="btn ghost" type="button" :disabled="busy || !form.model.trim() || !form.base_url" @click="probe">{{ probing ? '正在探测…' : form.capability_profile ? '重新探测' : '探测能力' }}</button></div><CapabilityReport v-if="form.capability_profile" :profile="form.capability_profile" /><p v-else class="model-unverified">{{ editing ? '当前配置尚未探测' : '填写连接设置后可探测模型能力' }}</p></section>
      </form>
      <template #footer><p v-if="error" class="error model-form-error" role="alert">{{ error }}</p><div class="model-dialog-footer">
        <template v-if="confirmDelete"><span class="model-delete-question">确认删除 {{ selectedModel?.model }}？</span><div class="row"><button class="btn ghost" type="button" :disabled="busy" @click="confirmDelete = false">取消</button><button class="btn model-delete-confirm" type="button" :disabled="busy" @click="remove(selectedModel)">{{ pending ? '正在删除…' : '确认删除' }}</button></div></template>
        <template v-else><div><button v-if="editing && !isForeign(selectedModel)" class="btn ghost model-delete" type="button" :disabled="busy || selectedModel?.is_default" :title="selectedModel?.is_default ? '请先切换默认模型' : undefined" @click="confirmDelete = true"><AppIcon name="trash" />删除</button></div><div class="row"><button v-if="viewOnly && !isForeign(selectedModel)" class="btn cta" type="button" @click="viewOnly = false">编辑配置</button><button v-else-if="!viewOnly" class="btn cta" type="submit" form="model-config-form" :disabled="busy">{{ pending ? '保存中…' : '保存配置' }}<AppIcon name="check" /></button><button v-else class="btn ghost" type="button" @click="drawerOpen = false">关闭</button></div></template>
      </div></template>
    </FormDrawer>
  </section>
</template>
<style src="../model-provider.css"></style>
