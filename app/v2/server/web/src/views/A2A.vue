<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const peers = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const hasPeers = computed(() => peers.value.length > 0)

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
    url: item.url || '',
    description: item.description || '',
    api_key: '',
    disabled: Boolean(item.disabled),
  }
}

function startNew() {
  editing.value = ''
  form.value = emptyForm()
}

async function refreshSkills(name) {
  error.value = ''
  try {
    await api.refreshA2aAgent(name)
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
}

async function toggle(item) {
  error.value = ''
  try {
    await api.updateA2aAgent(item.name, {
      name: item.name,
      url: item.url,
      description: item.description || '',
      api_key: '',
      disabled: !item.disabled,
    })
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
}

async function remove(name) {
  error.value = ''
  try {
    await api.deleteA2aAgent(name)
    if (editing.value === name) startNew()
    await refresh()
  } catch (exc) {
    error.value = exc.message
  }
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
      <h1>A2A</h1>
    </header>
    <form class="panel" @submit.prevent="save">
      <label class="field">
        <span>名称</span>
        <input v-model="form.name" :disabled="Boolean(editing)" required />
      </label>
      <label class="field">
        <span>地址</span>
        <input v-model="form.url" type="url" placeholder="https://peer.example.com" required />
        <small class="muted">
          填对方的 base URL，不是 JSON-RPC 端点：端点写在对方的 Agent Card 里。
        </small>
      </label>
      <label class="field">
        <span>描述</span>
        <input v-model="form.description" />
      </label>
      <label class="field">
        <span>API Key</span>
        <input v-model="form.api_key" type="password" autocomplete="off" />
        <small class="muted">
          只进不出。{{ editing ? '留空表示沿用已保存的凭据。' : '对方不需要鉴权时可留空。' }}
        </small>
      </label>
      <label class="row">
        <input v-model="form.disabled" type="checkbox" />
        停用（保留配置，但本租户的智能体看不到它的技能）
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="row">
        <button class="btn cta" type="submit" :disabled="pending">
          {{ editing ? '保存远端智能体' : '添加远端智能体' }}
        </button>
        <button v-if="editing" class="btn ghost" type="button" @click="startNew">新建另一个</button>
      </div>
    </form>
    <div class="panel stack">
      <h2>可委派</h2>
      <p v-if="!hasPeers" class="empty">
        还没有远端智能体。添加后每个技能会成为一个 <code>a2a_&lt;名称&gt;_&lt;技能&gt;</code> 工具。
      </p>
      <table v-else>
        <thead>
          <tr><th>名称</th><th>凭据</th><th>技能</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in peers" :key="item.name">
            <td>
              {{ item.name }}
              <span v-if="item.disabled" class="muted">（已停用）</span>
              <div class="muted">{{ item.description || item.url }}</div>
            </td>
            <td class="muted">{{ item.has_api_key ? '已保存' : '无' }}</td>
            <td class="muted">{{ (item.skills || []).join(', ') || '未刷新' }}</td>
            <td class="row">
              <button class="btn ghost" type="button" @click="refreshSkills(item.name)">刷新技能</button>
              <button class="btn ghost" type="button" @click="toggle(item)">
                {{ item.disabled ? '启用' : '停用' }}
              </button>
              <button class="btn ghost" type="button" @click="edit(item)">编辑</button>
              <button class="btn ghost" type="button" @click="remove(item.name)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="muted">
        委派会把消息发给另一个组织，撤不回来，所以第一次调用会先在对话里请求批准。
      </p>
    </div>
  </section>
</template>
