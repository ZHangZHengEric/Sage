<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import AppIcon from '../components/AppIcon.vue'
import FormDrawer from '../components/FormDrawer.vue'

const drawerOpen = ref(false)
const editing = ref(''), viewOnly = ref(false), selectedModel = ref(null)

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

const defaultBaseUrls = {
  'openai-chat-completions': 'https://api.openai.com/v1',
  'openai-responses': 'https://api.openai.com/v1',
  'anthropic-messages': 'https://api.anthropic.com',
  orcarouter: 'https://api.orcarouter.ai/v1',
}

function onProtocolChange() {
  if (!form.value.base_url || Object.values(defaultBaseUrls).includes(form.value.base_url)) {
    form.value.base_url = defaultBaseUrls[form.value.protocol]
  }
}

async function refresh() {
  models.value = await api.listModels()
}

async function save() {
  if (viewOnly.value || isForeign(selectedModel.value) || pending.value) return
  error.value = ''
  pending.value = true
  try {
    await api.saveModel({ ...form.value, ...(editing.value ? { id: editing.value } : {}), is_default: editing.value ? selectedModel.value.is_default : !models.value.some(item => !isForeign(item)) })
    form.value.api_key = ''
    await refresh()
    drawerOpen.value = false
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
function startNew() {
  editing.value = ''; viewOnly.value = false; selectedModel.value = null
  error.value = ''; form.value = { protocol: 'openai-chat-completions', base_url: 'https://api.openai.com/v1', model: '', api_key: '' }
  drawerOpen.value = true
}
async function openModel(item, readonly = true) {
  error.value = ''; pending.value = true
  try {
    const detail = await api.getModel(item.id, item._owner)
    editing.value = item.id; selectedModel.value = item
    form.value = { protocol: detail.protocol, base_url: detail.base_url, model: detail.model, api_key: detail.api_key }
    viewOnly.value = readonly || isForeign(item)
    drawerOpen.value = true
  } catch (exc) { error.value = exc.message }
  finally { pending.value = false }
}
</script>

<template>
  <section>
    <header class="page-head">
      <h1>模型供应商</h1><button class="btn cta" type="button" :disabled="pending" @click="startNew">新增模型</button>
    </header>
    <div class="panel table-panel">

      <p v-if="error && !drawerOpen" class="error" role="alert">{{ error }}</p>
      <p v-if="!hasModels" class="empty">还没有模型</p>
      <table v-else>
        <thead>
          <tr><th v-if="models[0]?._owner">用户</th><th>模型</th><th>协议</th><th>地址</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="item in models" :key="`${item._owner?.user_id || ''}:${item.id}`">
            <td v-if="models[0]?._owner">{{ item._owner?.username }}</td>
            <td>
              {{ item.model }}
              <span v-if="item.is_default && models.length > 1" class="tag">当前</span>
            </td>
            <td class="mono">{{ item.protocol }}</td>
            <td class="mono">{{ item.base_url }}</td>
            <td class="row">
              <button class="btn ghost" :disabled="pending" @click="openModel(item)">查看</button>
              <button v-if="!isForeign(item)" class="btn ghost" :disabled="pending" @click="openModel(item, false)">编辑</button>
              <button
                v-if="!isForeign(item) && !item.is_default && models.length > 1"
                class="btn ghost"
                type="button"
                @click="makeCurrent(item)"
              >
                设为当前
              </button>
              <button class="btn ghost" type="button" v-if="!isForeign(item)" @click="remove(item.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <FormDrawer v-model="drawerOpen" :title="viewOnly ? '查看模型配置' : editing ? '编辑模型配置' : '新增模型配置'" :busy="pending">
      <form class="model-detail" @submit.prevent="save">
        <aside class="model-summary"><span class="resource-icon"><AppIcon name="model" /></span><h2>{{ form.model || '新模型' }}</h2><span class="tag">{{ form.protocol }}</span><span v-if="selectedModel?.is_default" class="tag">默认模型</span></aside>
        <div class="model-fields">
          <label class="field"><span>协议</span><select v-model="form.protocol" :disabled="viewOnly || pending"><option value="openai-chat-completions">OpenAI Chat Completions</option><option value="openai-responses">OpenAI Responses</option><option value="anthropic-messages">Anthropic Messages</option><option value="orcarouter">OrcaRouter</option><option v-if="!['openai-chat-completions', 'openai-responses', 'anthropic-messages', 'orcarouter'].includes(form.protocol)" :value="form.protocol">{{ form.protocol }}</option></select></label>
          <label class="field"><span>API 地址</span><input v-model="form.base_url" :readonly="viewOnly" :disabled="pending" required /></label>
          <label class="field"><span>模型名称</span><input v-model="form.model" :readonly="viewOnly" :disabled="pending" required /></label>
          <label class="field"><span>API Key</span><textarea v-model="form.api_key" class="mono" :readonly="viewOnly" :disabled="pending" autocomplete="off" spellcheck="false" rows="3" required /></label>
          <p v-if="error" class="error" role="alert">{{ error }}</p>
          <button v-if="viewOnly && !isForeign(selectedModel)" class="btn" type="button" @click="viewOnly = false">编辑</button>
          <button v-else-if="!viewOnly" class="btn" type="submit" :disabled="pending">{{ pending ? '保存中…' : '保存配置' }}</button>
        </div>
      </form>
    </FormDrawer>
  </section>
</template>
<style scoped>
.model-detail { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 24px; }
.model-summary { align-self: start; padding: 20px; border: 1px solid var(--border); border-radius: 16px; background: color-mix(in srgb, var(--muted) 20%, white); }
.model-summary h2 { margin: 16px 0; overflow-wrap: anywhere; }
.model-summary .tag { margin: 0 6px 6px 0; border-radius: 999px; overflow-wrap: anywhere; }
.model-fields { min-width: 0; }
.model-fields textarea { white-space: pre-wrap; overflow-wrap: anywhere; resize: vertical; }
@media (max-width: 900px) { .model-detail { grid-template-columns: minmax(0, 1fr); } }
</style>
