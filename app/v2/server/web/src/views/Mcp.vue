<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, isForeign } from '../api.js'
import { getUser } from '../auth.js'
import ResourceDetails from '../components/ResourceDetails.vue'
import FormDrawer from '../components/FormDrawer.vue'
import ToolSources from '../components/ToolSources.vue'
import AppIcon from '../components/AppIcon.vue'
import FieldHelp from '../components/FieldHelp.vue'
import ToolDetail from '../components/ToolDetail.vue'
import { mcpServerKey, mcpToolInventory } from '../mcp-presentation.js'
import { resourceHelp } from '../resource-presentation.js'

const drawerOpen = ref(false), deleteTarget = ref(null), loading = ref(true), search = ref('')
const mode = ref('tools'), serverFilter = ref(''), catalogs = ref([])
const toolsLoading = ref(false), toolErrors = ref([]), toolsLoaded = ref(false)
const selectedTool = ref(null), toolDetailOpen = ref(false)
let toolSequence = 0, disposed = false
const currentUserId = getUser()?.user_id || ''

const servers = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const visibleServers = computed(() => servers.value.filter(item => `${item.name} ${item.description || ''} ${item.url || ''}`.toLowerCase().includes(search.value.toLowerCase())))
const inventory = computed(() => mcpToolInventory(servers.value, catalogs.value, currentUserId))
const visibleTools = computed(() => inventory.value.filter(row =>
  (!serverFilter.value || row.serverKey === serverFilter.value) &&
  `${row.tool.name} ${row.tool.description || ''} ${row.serverName} ${row.owner?.username || ''}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const states = { available: '已取得定义', disabled: '服务已停用', unknown: '当前定义未确认' }
function serverKey(item) { return mcpServerKey(item, currentUserId) }
function showTools(item) { search.value = ''; serverFilter.value = serverKey(item); mode.value = 'tools' }
function inspectTool(row) { selectedTool.value = row.tool; toolDetailOpen.value = true }
async function loadDefinitions() {
  if (disposed || toolsLoading.value) return
  const sequence = ++toolSequence
  toolsLoading.value = true; toolErrors.value = []
  const owners = new Map()
  for (const item of servers.value.filter(item => !item.disabled)) owners.set(item._owner?.user_id || currentUserId, item._owner)
  const results = await Promise.all([...owners.values()].map(async owner => {
    try { return { owner, tools: (await api.listTools(owner)).filter(tool => tool.source === 'mcp') } }
    catch (exc) { return { owner, tools: [], error: `${owner?.username || '当前用户'}：${exc.message}` } }
  }))
  if (sequence !== toolSequence) return
  catalogs.value = results
  toolErrors.value = results.filter(result => result.error).map(result => result.error)
  toolsLoading.value = false; toolsLoaded.value = true
}
watch(mode, value => { search.value = ''; if (value === 'tools' && !toolsLoaded.value) void loadDefinitions() })
onBeforeUnmount(() => { disposed = true; toolSequence++ })

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
  const nextServers = await api.listMcp()
  if (disposed) return
  servers.value = nextServers
  if (serverFilter.value !== 'unmatched' && !servers.value.some(item => serverKey(item) === serverFilter.value)) serverFilter.value = ''
  toolSequence++; toolsLoading.value = false; toolsLoaded.value = false; catalogs.value = []
  if (mode.value === 'tools') void loadDefinitions()
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
  <section class="resource-page" aria-label="MCP 服务">
    <PageToolbar aria-label="MCP 服务操作">
      <ToolSources />
      <template #actions>
        <label class="rs-search"><AppIcon name="search" /><input v-model="search" type="search" :aria-label="mode === 'tools' ? '搜索 MCP 工具' : '搜索 MCP 服务'" :placeholder="mode === 'tools' ? '搜索工具或用途' : '搜索 MCP 服务'" /></label>
        <button v-if="mode === 'tools'" class="btn ghost" type="button" :disabled="loading || toolsLoading || pending" @click="loadDefinitions"><AppIcon name="refresh" />刷新列表</button>
        <button class="btn cta" type="button" :disabled="pending" @click="startNew"><AppIcon name="plus" />添加 MCP</button>
      </template>
      <template #filters>
        <div class="rs-filters" aria-label="MCP 展示方式"><button v-for="[value, label] in [['tools', '工具列表'], ['connections', '服务连接']]" :key="value" type="button" :aria-pressed="mode === value" @click="mode = value">{{ label }}</button></div>
        <select v-if="mode === 'tools'" v-model="serverFilter" class="rs-service-filter" aria-label="按 MCP 服务筛选"><option value="">全部服务</option><option v-for="item in servers" :key="serverKey(item)" :value="serverKey(item)">{{ item.name }}{{ item._owner ? ` · ${item._owner.username}` : '' }}{{ item.disabled ? '（已停用）' : '' }}</option><option v-if="inventory.some(row => row.serverKey === 'unmatched')" value="unmatched">未匹配服务</option></select>
      </template>
    </PageToolbar>
    <p v-if="error && !drawerOpen && !deleteTarget" class="error" role="alert">{{ error }}</p>
    <template v-if="mode === 'tools'">
      <p v-if="toolsLoading" class="rs-catalog-status" role="status">正在加载工具定义…</p>
      <p v-if="toolErrors.length" class="error" role="alert">{{ toolErrors.join('；') }}。仍保留服务已发现的工具名称。<button class="btn ghost" type="button" :disabled="toolsLoading" @click="loadDefinitions">重试</button></p>
      <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载 MCP 工具"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
      <div v-else-if="!visibleTools.length" class="rs-empty"><span class="rs-icon"><AppIcon name="tools" /></span><h2>{{ search || serverFilter ? '没有匹配的 MCP 工具' : toolsLoading ? '正在读取工具目录' : servers.length ? '尚未发现 MCP 工具' : '连接你的第一个 MCP 服务' }}</h2><button v-if="search || serverFilter" class="btn ghost" type="button" @click="search = ''; serverFilter = ''">清除筛选</button><button v-else-if="!servers.length && !error" class="btn cta" type="button" @click="startNew">添加 MCP</button><button v-else-if="error" class="btn ghost" type="button" @click="load">重新加载</button><button v-else class="btn ghost" type="button" @click="mode = 'connections'">查看服务连接</button></div>
      <div v-else class="rs-grid" aria-label="MCP 工具列表"><article v-for="row in visibleTools" :key="row.key" class="rs-card"><header class="rs-card-head"><span class="rs-icon"><AppIcon name="tools" /></span><div><h2>{{ row.tool.name }}</h2><div class="rs-technical">{{ row.serverName }}<span v-if="row.owner"> · {{ row.owner.username }}</span></div></div></header><p class="rs-description">{{ row.tool.description || (row.state === 'disabled' ? '服务已停用，保留上次发现的工具名称。' : '尚未取得当前工具定义，可在服务连接中刷新工具。') }}</p><div class="rs-tags"><span class="rs-badge neutral">{{ states[row.state] }}</span><span v-if="row.owner && row.owner.user_id !== currentUserId" class="rs-badge readonly">只读</span></div><footer class="rs-card-footer"><span>MCP 工具</span><button v-if="row.hasDefinition" class="btn ghost" type="button" :aria-label="`查看 ${row.tool.name} 的参数`" @click="inspectTool(row)">查看参数<AppIcon name="chevron" /></button><button v-else-if="row.server && !isForeign(row.server)" class="btn ghost" type="button" :disabled="pending" @click="refreshTools(row.server)">刷新工具</button></footer></article></div>
    </template>
    <template v-else>
    <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载 MCP 服务"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="!visibleServers.length" class="rs-empty"><span class="rs-icon"><AppIcon name="link" /></span><h2>{{ search ? '没有匹配的 MCP 服务' : error ? '暂时无法加载连接' : '连接你的第一个 MCP 服务' }}</h2><button v-if="error" class="btn ghost" type="button" @click="load">重新加载</button><button v-else-if="search" class="btn ghost" type="button" @click="search = ''">清除搜索</button><button v-else class="btn cta" type="button" @click="startNew">添加 MCP</button></div>
    <div v-else class="rs-grid"><article v-for="item in visibleServers" :key="`${item._owner?.user_id || ''}:${item.name}`" class="rs-card"><header class="rs-card-head"><span class="rs-icon" data-tone="blue"><AppIcon name="link" /></span><div><h2>{{ item.name }}</h2><div class="rs-technical">{{ item.protocol }}<span v-if="item._owner"> · {{ item._owner.username }}</span></div></div></header><p class="rs-description">{{ item.description || item.url }}</p><div class="rs-tags"><span class="rs-badge neutral">{{ item.tools?.length || 0 }} 个工具</span><span v-if="item.disabled" class="rs-badge neutral">已停用</span><span v-if="isForeign(item)" class="rs-badge readonly">只读</span></div><footer class="rs-card-footer"><div class="row"><ResourceDetails :item="item" kind="mcp" @edit="edit" /><button class="btn ghost" type="button" :aria-label="`查看 ${item.name} 的工具`" @click="showTools(item)">查看工具</button></div><div v-if="!isForeign(item)" class="row"><button class="btn ghost" type="button" :disabled="pending" @click="refreshTools(item)">刷新工具</button><button class="icon-button" type="button" :disabled="pending" :aria-label="`删除 ${item.name}`" @click="error = ''; deleteTarget = item"><AppIcon name="trash" /></button></div></footer></article></div>
    </template>
    <ToolDetail v-model="toolDetailOpen" :item="selectedTool" />
    <FormDrawer v-model="drawerOpen" centered panel-class="resource-dialog import-dialog" :title="editing ? '编辑 MCP 连接' : '添加 MCP'" :busy="pending"><form v-if="drawerOpen" id="mcp-config-form" @submit.prevent="save"><div class="field"><div class="rs-label"><label for="mcp-name">名称</label><FieldHelp label="连接名称" :text="resourceHelp.name" /></div><input id="mcp-name" v-model="form.name" :disabled="Boolean(editing) || pending" required /></div><div class="field"><div class="rs-label"><label for="mcp-protocol">连接协议</label><FieldHelp label="连接协议" :text="resourceHelp.protocol" /></div><select id="mcp-protocol" v-model="form.protocol" :disabled="pending"><option value="streamable_http">Streamable HTTP</option><option value="sse">SSE</option></select></div><div class="field"><div class="rs-label"><label for="mcp-url">服务地址</label><FieldHelp label="服务地址" :text="resourceHelp.url" /></div><input id="mcp-url" v-model="form.url" :disabled="pending" type="url" placeholder="https://example.com/mcp" required /></div><div class="field"><div class="rs-label"><label for="mcp-description">描述</label><FieldHelp label="连接描述" :text="resourceHelp.description" /></div><input id="mcp-description" v-model="form.description" :disabled="pending" /></div><div class="field"><div class="rs-label"><label for="mcp-key">API Key</label><FieldHelp label="API Key" :text="resourceHelp.key" /></div><input id="mcp-key" v-model="form.api_key" :disabled="pending" type="password" autocomplete="off" :placeholder="editing ? '留空保留已保存的密钥' : '按服务的认证要求填写'" /></div><div class="rs-form-grid"><div class="field"><div class="rs-label"><label for="mcp-timeout">连接超时（秒）</label><FieldHelp label="连接超时" :text="resourceHelp.timeout" /></div><input id="mcp-timeout" type="number" min="0" max="900" step="any" :disabled="pending" :value="form.timeout_seconds" @input="form.timeout_seconds = $event.target.value === '' ? null : Number($event.target.value)" placeholder="服务默认" /></div><div class="field"><div class="rs-label"><label for="mcp-call-timeout">调用超时（秒）</label><FieldHelp label="调用超时" :text="resourceHelp.callTimeout" /></div><input id="mcp-call-timeout" type="number" min="0" step="any" :disabled="pending" :value="form.call_timeout_seconds" @input="form.call_timeout_seconds = $event.target.value === '' ? null : Number($event.target.value)" placeholder="服务默认" /></div></div></form><template #footer><p v-if="error" class="error rs-footer-error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><span></span><button class="btn cta" type="submit" form="mcp-config-form" :disabled="pending">{{ pending ? '保存中…' : '保存连接' }}</button></div></template></FormDrawer>
    <FormDrawer :model-value="!!deleteTarget" centered panel-class="resource-dialog import-dialog" title="删除 MCP 连接" :busy="pending" @update:model-value="deleteTarget = null"><p>确认删除 {{ deleteTarget?.name }}？关联工具将不再由此连接提供。</p><template #footer><p v-if="error" class="error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><button class="btn ghost" type="button" :disabled="pending" @click="deleteTarget = null">取消</button><button class="btn rs-destructive" type="button" :disabled="pending" @click="remove">确认删除</button></div></template></FormDrawer>
  </section>
</template>
<style src="../resource-surfaces.css"></style>
