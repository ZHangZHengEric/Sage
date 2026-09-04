<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const servers = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const hasServers = computed(() => servers.value.length > 0)

function emptyForm() {
  return {
    name: '',
    protocol: 'stdio',
    url: '',
    command: '',
    argsText: '',
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
      command: form.value.command || null,
      args: form.value.argsText.split(/\s+/).filter(Boolean),
      description: form.value.description,
      api_key: form.value.api_key,
    }
    if (editing.value) await api.updateMcp(editing.value, payload)
    else await api.createMcp(payload)
    editing.value = ''
    form.value = emptyForm()
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

function edit(item) {
  editing.value = item.name
  form.value = {
    name: item.name,
    protocol: item.protocol,
    url: item.url || '',
    command: item.command || '',
    argsText: (item.args || []).join(' '),
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
</script>

<template>
  <section>
    <header class="page-head">
      <h1>MCP</h1>
    </header>
    <form class="panel" @submit.prevent="save">
      <label class="field">
        <span>名称</span>
        <input v-model="form.name" :disabled="Boolean(editing)" required />
      </label>
      <label class="field">
        <span>协议</span>
        <select v-model="form.protocol">
          <option value="stdio">stdio</option>
          <option value="sse">sse</option>
          <option value="streamable_http">streamable_http</option>
        </select>
      </label>
      <label v-if="form.protocol === 'stdio'" class="field">
        <span>命令</span>
        <input v-model="form.command" required />
      </label>
      <label v-else class="field">
        <span>URL</span>
        <input v-model="form.url" required />
      </label>
      <label class="field">
        <span>参数</span>
        <input v-model="form.argsText" placeholder="空格分隔" />
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
    <div class="panel stack">
      <h2>已连接</h2>
      <p v-if="!hasServers" class="empty">还没有 MCP。添加后可在智能体页勾选工具。</p>
      <table v-else>
        <thead>
          <tr><th>名称</th><th>协议</th><th>工具</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in servers" :key="item.name">
            <td>
              {{ item.name }}
              <div class="muted">{{ item.description || item.command || item.url }}</div>
            </td>
            <td>{{ item.protocol }}</td>
            <td class="muted">{{ (item.tools || []).join(', ') || '未刷新' }}</td>
            <td class="row">
              <button class="btn ghost" type="button" @click="refreshTools(item.name)">刷新工具</button>
              <button class="btn ghost" type="button" @click="edit(item)">编辑</button>
              <button class="btn ghost" type="button" @click="remove(item.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
