<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import ResourceDetails from '../components/ResourceDetails.vue'
import FormDrawer from '../components/FormDrawer.vue'
import ToolSources from '../components/ToolSources.vue'
import AppIcon from '../components/AppIcon.vue'
import FieldHelp from '../components/FieldHelp.vue'
import { resourceHelp } from '../resource-presentation.js'

const drawerOpen = ref(false), deleteTarget = ref(null), loading = ref(true), search = ref('')

const servers = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const visibleServers = computed(() => servers.value.filter(item => `${item.name} ${item.description || ''} ${item.url || ''}`.toLowerCase().includes(search.value.toLowerCase())))

function emptyForm() {
  return {
    name: '',
    protocol: 'streamable_http',
    url: '',
    description: '',
    api_key: '',
    timeout_seconds: 30,
    call_timeout_seconds: null,
  }
}

async function refresh() {
  servers.value = await api.listMcp()
}

async function save() {
  if (pending.value) return
  error.value = ''
  pending.value = true
  try {
    const payload = {
      name: form.value.name,
      protocol: form.value.protocol,
      url: form.value.url || null,
      description: form.value.description,
      api_key: form.value.api_key,
      timeout_seconds: form.value.timeout_seconds,
      call_timeout_seconds: form.value.call_timeout_seconds,
    }
    if (editing.value) await api.updateMcp(editing.value, payload)
    else await api.createMcp(payload)
    editing.value = ''
    form.value = emptyForm()
    await refresh()
    drawerOpen.value = false
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

function edit(item) {
  if (isForeign(item) || pending.value) return
  drawerOpen.value = true
  error.value = ''
  editing.value = item.name
  form.value = {
    name: item.name,
    protocol: item.protocol,
    url: item.url || '',
    description: item.description || '',
    api_key: '',
    timeout_seconds: item.timeout_seconds ?? 30,
    call_timeout_seconds: item.call_timeout_seconds ?? null,
  }
}

async function refreshTools(item) {
  if (isForeign(item) || pending.value) return
  error.value = ''; pending.value = true
  try { await api.refreshMcp(item.name); await refresh() } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function remove() {
  const item = deleteTarget.value
  if (!item || isForeign(item) || pending.value) return
  error.value = ''; pending.value = true
  try { await api.deleteMcp(item.name); deleteTarget.value = null; await refresh() } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try { await refresh() } catch (exc) { error.value = exc.message } finally { loading.value = false }
}
onMounted(load)
function startNew() {
  if (pending.value) return
  error.value = ''; editing.value = ''; form.value = emptyForm()
  drawerOpen.value = true
}
</script>

<template>
  <section class="resource-page"><header class="page-head rs-page-head"><div class="rs-heading"><h1>工具</h1><span v-if="!loading" class="rs-count">{{ servers.length }}</span></div><button class="btn cta" type="button" :disabled="pending" @click="startNew"><AppIcon name="plus" />添加 MCP</button></header><ToolSources /><div class="rs-toolbar"><span class="rs-small muted">MCP 服务</span><label class="rs-search"><AppIcon name="search" /><input v-model="search" type="search" aria-label="搜索 MCP 服务" placeholder="搜索 MCP 服务" /></label></div>
    <p v-if="error && !drawerOpen && !deleteTarget" class="error" role="alert">{{ error }}</p>
    <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载 MCP 服务"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="!visibleServers.length" class="rs-empty"><span class="rs-icon"><AppIcon name="link" /></span><h2>{{ search ? '没有匹配的 MCP 服务' : error ? '暂时无法加载连接' : '连接你的第一个 MCP 服务' }}</h2><button v-if="error" class="btn ghost" type="button" @click="load">重新加载</button><button v-else-if="search" class="btn ghost" type="button" @click="search = ''">清除搜索</button><button v-else class="btn cta" type="button" @click="startNew">添加 MCP</button></div>
    <div v-else class="rs-grid"><article v-for="item in visibleServers" :key="`${item._owner?.user_id || ''}:${item.name}`" class="rs-card"><header class="rs-card-head"><span class="rs-icon" data-tone="blue"><AppIcon name="link" /></span><div><h2>{{ item.name }}</h2><div class="rs-technical">{{ item.protocol }}<span v-if="item._owner"> · {{ item._owner.username }}</span></div></div></header><p class="rs-description">{{ item.description || item.url }}</p><div class="rs-tags"><span class="rs-badge neutral">{{ item.tools?.length || 0 }} 个工具</span><span v-if="item.disabled" class="rs-badge neutral">已停用</span><span v-if="isForeign(item)" class="rs-badge readonly">只读</span></div><footer class="rs-card-footer"><ResourceDetails :item="item" kind="mcp" @edit="edit" /><div v-if="!isForeign(item)" class="row"><button class="btn ghost" type="button" :disabled="pending" @click="refreshTools(item)">刷新工具</button><button class="icon-button" type="button" :disabled="pending" :aria-label="`删除 ${item.name}`" @click="error = ''; deleteTarget = item"><AppIcon name="trash" /></button></div></footer></article></div>
    <FormDrawer v-model="drawerOpen" centered panel-class="resource-dialog import-dialog" :title="editing ? '编辑 MCP 连接' : '添加 MCP'" :busy="pending"><form v-if="drawerOpen" id="mcp-config-form" @submit.prevent="save"><div class="field"><div class="rs-label"><label for="mcp-name">名称</label><FieldHelp label="连接名称" :text="resourceHelp.name" /></div><input id="mcp-name" v-model="form.name" :disabled="Boolean(editing) || pending" required /></div><div class="field"><div class="rs-label"><label for="mcp-protocol">连接协议</label><FieldHelp label="连接协议" :text="resourceHelp.protocol" /></div><select id="mcp-protocol" v-model="form.protocol" :disabled="pending"><option value="streamable_http">Streamable HTTP</option><option value="sse">SSE</option></select></div><div class="field"><div class="rs-label"><label for="mcp-url">服务地址</label><FieldHelp label="服务地址" :text="resourceHelp.url" /></div><input id="mcp-url" v-model="form.url" :disabled="pending" type="url" placeholder="https://example.com/mcp" required /></div><div class="field"><div class="rs-label"><label for="mcp-description">描述</label><FieldHelp label="连接描述" :text="resourceHelp.description" /></div><input id="mcp-description" v-model="form.description" :disabled="pending" /></div><div class="field"><div class="rs-label"><label for="mcp-key">API Key</label><FieldHelp label="API Key" :text="resourceHelp.key" /></div><input id="mcp-key" v-model="form.api_key" :disabled="pending" type="password" autocomplete="off" :placeholder="editing ? '留空保留已保存的密钥' : '按服务的认证要求填写'" /></div><div class="rs-form-grid"><div class="field"><div class="rs-label"><label for="mcp-timeout">连接超时（秒）</label><FieldHelp label="连接超时" :text="resourceHelp.timeout" /></div><input id="mcp-timeout" type="number" min="0" max="900" step="any" :disabled="pending" :value="form.timeout_seconds" @input="form.timeout_seconds = $event.target.value === '' ? null : Number($event.target.value)" placeholder="服务默认" /></div><div class="field"><div class="rs-label"><label for="mcp-call-timeout">调用超时（秒）</label><FieldHelp label="调用超时" :text="resourceHelp.callTimeout" /></div><input id="mcp-call-timeout" type="number" min="0" step="any" :disabled="pending" :value="form.call_timeout_seconds" @input="form.call_timeout_seconds = $event.target.value === '' ? null : Number($event.target.value)" placeholder="服务默认" /></div></div></form><template #footer><p v-if="error" class="error rs-footer-error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><span></span><button class="btn cta" type="submit" form="mcp-config-form" :disabled="pending">{{ pending ? '保存中…' : '保存连接' }}</button></div></template></FormDrawer>
    <FormDrawer :model-value="!!deleteTarget" centered panel-class="resource-dialog import-dialog" title="删除 MCP 连接" :busy="pending" @update:model-value="deleteTarget = null"><p>确认删除 {{ deleteTarget?.name }}？关联工具将不再由此连接提供。</p><template #footer><p v-if="error" class="error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><button class="btn ghost" type="button" :disabled="pending" @click="deleteTarget = null">取消</button><button class="btn rs-destructive" type="button" :disabled="pending" @click="remove">确认删除</button></div></template></FormDrawer>
  </section>
</template>
<style src="../resource-surfaces.css"></style>
