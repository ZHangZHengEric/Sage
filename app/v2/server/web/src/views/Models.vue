<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const models = ref([])
const error = ref('')
const pending = ref(false)
const form = ref({
  protocol: 'openai-chat-completions',
  base_url: 'https://api.openai.com/v1',
  model: '',
  api_key: '',
})

const hasModels = computed(() => models.value.length > 0)

async function refresh() {
  models.value = await api.listModels()
}

async function save() {
  error.value = ''
  pending.value = true
  try {
    await api.saveModel({ ...form.value, is_default: !hasModels.value })
    form.value.api_key = ''
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

async function makeCurrent(item) {
  await api.saveModel({
    id: item.id,
    protocol: item.protocol,
    base_url: item.base_url,
    model: item.model,
    api_key: '',
    is_default: true,
  })
  await refresh()
}

async function remove(id) {
  await api.deleteModel(id)
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
      <h1>模型</h1>
    </header>
    <form class="panel" @submit.prevent="save">
      <label class="field">
        <span>协议</span>
        <select v-model="form.protocol">
          <option value="openai-chat-completions">openai-chat-completions</option>
          <option value="openai-responses">openai-responses</option>
          <option value="anthropic-messages">anthropic-messages</option>
        </select>
      </label>
      <label class="field">
        <span>Base URL</span>
        <input v-model="form.base_url" required />
      </label>
      <label class="field">
        <span>Model</span>
        <input v-model="form.model" required />
      </label>
      <label class="field">
        <span>API Key</span>
        <input v-model="form.api_key" type="password" autocomplete="off" required />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn cta" type="submit" :disabled="pending">上传模型</button>
    </form>
    <div class="panel stack">
      <h2>已上传</h2>
      <p v-if="!hasModels" class="empty">还没有模型</p>
      <table v-else>
        <thead>
          <tr><th>模型</th><th>协议</th><th>地址</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in models" :key="item.id">
            <td>
              {{ item.model }}
              <span v-if="item.is_default && models.length > 1" class="tag">当前</span>
            </td>
            <td class="mono">{{ item.protocol }}</td>
            <td class="mono">{{ item.base_url }}</td>
            <td class="row">
              <button
                v-if="!item.is_default && models.length > 1"
                class="btn ghost"
                type="button"
                @click="makeCurrent(item)"
              >
                设为当前
              </button>
              <button class="btn ghost" type="button" @click="remove(item.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
