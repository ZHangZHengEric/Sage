<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import ResourceDetails from '../components/ResourceDetails.vue'
import FormDrawer from '../components/FormDrawer.vue'
import ToolSources from '../components/ToolSources.vue'

const drawerOpen = ref(false)

const servers = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const hasServers = computed(() => servers.value.length > 0)

function emptyForm() {
  return {
    name: '',
    protocol: 'streamable_http',
    url: '',
    description: '',
    api_key: '',
  }
}

async function refresh() {
  servers.value = await api.listMcp()
}

async function save() {
  error.value = ''
  pending.value = true
  try {
    const payload = {
      name: form.value.name,
      protocol: form.value.protocol,
      url: form.value.url || null,
      description: form.value.description,
      api_key: form.value.api_key,
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
  drawerOpen.value = true
  error.value = ''
  editing.value = item.name
  form.value = {
    name: item.name,
    protocol: item.protocol,
    url: item.url || '',
    description: item.description || '',
    api_key: '',
  }
}

async function refreshTools(name) {
  error.value = ''
  try {
    await api.refreshMcp(name)
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
}

async function remove(name) {
  await api.deleteMcp(name)
  if (editing.value === name) {
    editing.value = ''
    form.value = emptyForm()
  }
  await refresh()
}

onMounted(async () => {
  try {
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
})
function startNew() {
  error.value = ''; editing.value = ''; form.value = emptyForm()
  drawerOpen.value = true
}
</script>

<template>
  <section>
    <header class="page-head">
      <h1>工具</h1><button class="btn cta" type="button" :disabled="pending" @click="startNew">新增 MCP</button>
    </header>
    <ToolSources />
    <div class="panel table-panel">

      <p v-if="error && !drawerOpen" class="error" role="alert">{{ error }}</p>
      <p v-if="!hasServers" class="empty">还没有 MCP。添加后请在智能体的「可用工具 → 外部工具」中勾选授权。</p>
      <table v-else>
        <thead>
          <tr><th v-if="servers[0]?._owner">用户</th><th>名称</th><th>协议</th><th>工具</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in servers" :key="`${item._owner?.user_id || ''}:${item.name}`">
            <td v-if="servers[0]?._owner">{{ item._owner?.username }}</td>
            <td>
              {{ item.name }}
              <div class="muted">{{ item.description || item.url }}</div>
            </td>
            <td>{{ item.protocol }}</td>
            <td class="muted">{{ (item.tools || []).join(', ') || '未刷新' }}</td>
            <td class="row">
              <ResourceDetails :item="item" kind="mcp" />
              <button class="btn ghost" type="button" v-if="!isForeign(item)" @click="refreshTools(item.name)">刷新工具</button>
              <button class="btn ghost" type="button" v-if="!isForeign(item)" @click="edit(item)">编辑</button>
              <button class="btn ghost" type="button" v-if="!isForeign(item)" @click="remove(item.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <FormDrawer v-model="drawerOpen" :title="editing ? '编辑 MCP' : '新增 MCP'" :busy="pending">
    <form class="panel" @submit.prevent="save">
      <label class="field">
        <span>名称</span>
        <input v-model="form.name" :disabled="Boolean(editing)" required />
      </label>
      <label class="field">
        <span>协议</span>
        <select v-model="form.protocol">
          <option value="streamable_http">streamable_http</option>
          <option value="sse">sse</option>
        </select>
      </label>
      <label class="field">
        <span>URL</span>
        <input v-model="form.url" type="url" placeholder="https://example.com/mcp" required />
      </label>
      <label class="field">
        <span>描述</span>
        <input v-model="form.description" />
      </label>
      <label class="field">
        <span>API Key</span>
        <input v-model="form.api_key" type="password" autocomplete="off" />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn cta" type="submit" :disabled="pending">
        {{ editing ? '保存连接' : '添加 MCP' }}
      </button>
    </form>
    </FormDrawer>
  </section>
</template>
