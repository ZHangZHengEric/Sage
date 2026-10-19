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

const peers = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const visiblePeers = computed(() => peers.value.filter(item => `${item.name} ${item.description || ''} ${item.url || ''}`.toLowerCase().includes(search.value.toLowerCase())))

function emptyForm() {
  return {
    name: '',
    url: '',
    description: '',
    api_key: '',
    disabled: false,
  }
}

async function refresh() {
  peers.value = await api.listA2aAgents()
}

async function save() {
  if (pending.value) return
  error.value = ''
  pending.value = true
  try {
    const payload = {
      name: form.value.name,
      url: form.value.url,
      description: form.value.description,
      // An empty key on save means "leave it alone": the list never returns
      // the key, so a form that echoed it back would have nothing to echo.
      api_key: form.value.api_key,
      disabled: form.value.disabled,
    }
    if (editing.value) await api.updateA2aAgent(editing.value, payload)
    else await api.createA2aAgent(payload)
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
    url: item.url || '',
    description: item.description || '',
    api_key: '',
    disabled: Boolean(item.disabled),
  }
}

function startNew() {
  if (pending.value) return
  drawerOpen.value = true
  error.value = ''
  editing.value = ''
  form.value = emptyForm()
}

async function refreshSkills(item) {
  if (isForeign(item) || pending.value) return
  error.value = ''; pending.value = true
  try { await api.refreshA2aAgent(item.name); await refresh() } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function toggle(item) {
  if (isForeign(item) || pending.value) return
  error.value = ''; pending.value = true
  try { await api.updateA2aAgent(item.name, { name: item.name, url: item.url, description: item.description || '', api_key: '', disabled: !item.disabled }); await refresh() } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function remove() {
  const item = deleteTarget.value
  if (!item || isForeign(item) || pending.value) return
  error.value = ''; pending.value = true
  try { await api.deleteA2aAgent(item.name); deleteTarget.value = null; await refresh() } catch (exc) { error.value = exc.message } finally { pending.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try { await refresh() } catch (exc) { error.value = exc.message } finally { loading.value = false }
}
onMounted(load)
</script>
<template>
  <section class="resource-page"><header class="page-head rs-page-head"><div class="rs-heading"><h1>工具</h1><span v-if="!loading" class="rs-count">{{ peers.length }}</span></div><button class="btn cta" type="button" :disabled="pending" @click="startNew"><AppIcon name="plus" />添加远端智能体</button></header><ToolSources /><div class="rs-toolbar"><span class="rs-small muted">远端智能体</span><label class="rs-search"><AppIcon name="search" /><input v-model="search" type="search" aria-label="搜索远端智能体" placeholder="搜索远端智能体" /></label></div>
    <p v-if="error && !drawerOpen && !deleteTarget" class="error" role="alert">{{ error }}</p>
    <div v-if="loading" class="rs-grid" aria-busy="true" aria-label="正在加载远端智能体"><div v-for="n in 3" :key="n" class="rs-skeleton"><i></i><i></i><i></i></div></div>
    <div v-else-if="!visiblePeers.length" class="rs-empty"><span class="rs-icon"><AppIcon name="agent" /></span><h2>{{ search ? '没有匹配的远端智能体' : error ? '暂时无法加载连接' : '连接你的第一个远端智能体' }}</h2><button v-if="error" class="btn ghost" type="button" @click="load">重新加载</button><button v-else-if="search" class="btn ghost" type="button" @click="search = ''">清除搜索</button><button v-else class="btn cta" type="button" @click="startNew">添加远端智能体</button></div>
    <div v-else class="rs-grid"><article v-for="item in visiblePeers" :key="`${item._owner?.user_id || ''}:${item.name}`" class="rs-card"><header class="rs-card-head"><span class="rs-icon" data-tone="clay"><AppIcon name="agent" /></span><div><h2>{{ item.name }}</h2><div class="rs-technical">A2A<span v-if="item._owner"> · {{ item._owner.username }}</span></div></div></header><p class="rs-description">{{ item.description || item.url }}</p><div class="rs-tags"><span class="rs-badge neutral">{{ item.skills?.length || 0 }} 项能力</span><span v-if="item.disabled" class="rs-badge neutral">已停用</span><span v-if="isForeign(item)" class="rs-badge readonly">只读</span></div><footer class="rs-card-footer"><ResourceDetails :item="item" kind="a2a" @edit="edit" /><div v-if="!isForeign(item)" class="row"><button class="btn ghost" type="button" :disabled="pending" @click="refreshSkills(item)">刷新</button><button class="btn ghost" type="button" :disabled="pending" @click="toggle(item)">{{ item.disabled ? '启用' : '停用' }}</button><button class="icon-button" type="button" :disabled="pending" :aria-label="`删除 ${item.name}`" @click="error = ''; deleteTarget = item"><AppIcon name="trash" /></button></div></footer></article></div>
    <FormDrawer v-model="drawerOpen" centered panel-class="resource-dialog import-dialog" :title="editing ? '编辑远端连接' : '添加远端智能体'" :busy="pending"><form v-if="drawerOpen" id="a2a-config-form" @submit.prevent="save"><div class="field"><div class="rs-label"><label for="a2a-name">名称</label><FieldHelp label="连接名称" :text="resourceHelp.name" /></div><input id="a2a-name" v-model="form.name" :disabled="Boolean(editing) || pending" required /></div><div class="field"><div class="rs-label"><label for="a2a-url">Base URL</label><FieldHelp label="服务地址" :text="resourceHelp.url" /></div><input id="a2a-url" v-model="form.url" :disabled="pending" type="url" placeholder="https://peer.example.com" required /></div><div class="field"><div class="rs-label"><label for="a2a-description">描述</label><FieldHelp label="连接描述" :text="resourceHelp.description" /></div><input id="a2a-description" v-model="form.description" :disabled="pending" /></div><div class="field"><div class="rs-label"><label for="a2a-key">API Key</label><FieldHelp label="API Key" :text="resourceHelp.key" /></div><input id="a2a-key" v-model="form.api_key" :disabled="pending" type="password" autocomplete="off" :placeholder="editing ? '留空保留已保存的密钥' : '对方不需要认证时可留空'" /></div><div class="rs-connection-toggle"><label><input v-model="form.disabled" type="checkbox" :disabled="pending" />停用连接</label><FieldHelp label="停用连接" :text="resourceHelp.disabled" /></div></form><template #footer><p v-if="error" class="error rs-footer-error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><span></span><button class="btn cta" type="submit" form="a2a-config-form" :disabled="pending">{{ pending ? '保存中…' : '保存连接' }}</button></div></template></FormDrawer>
    <FormDrawer :model-value="!!deleteTarget" centered panel-class="resource-dialog import-dialog" title="删除远端连接" :busy="pending" @update:model-value="deleteTarget = null"><p>确认删除 {{ deleteTarget?.name }}？此连接将不再提供远端能力。</p><template #footer><p v-if="error" class="error" role="alert">{{ error }}</p><div class="rs-dialog-footer"><button class="btn ghost" type="button" :disabled="pending" @click="deleteTarget = null">取消</button><button class="btn rs-destructive" type="button" :disabled="pending" @click="remove">确认删除</button></div></template></FormDrawer>
  </section>
</template>
<style src="../resource-surfaces.css"></style>
