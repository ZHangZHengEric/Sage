<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const keys = ref([]), agents = ref([]), busy = ref(false), error = ref(''), issued = ref('')
const form = ref({ name: '', agent_id: '', approve: false })

async function refresh() {
  const [nextKeys, nextAgents] = await Promise.all([api.listKeys(), api.listAgents()])
  keys.value = nextKeys; agents.value = nextAgents
  if (!form.value.agent_id) form.value.agent_id = nextAgents[0]?.id || ''
}
async function create() {
  busy.value = true; error.value = ''; issued.value = ''
  try {
    const result = await api.createKey({ name: form.value.name, agent_id: form.value.agent_id,
      scopes: ['a2a:invoke', 'a2a:read', ...(form.value.approve ? ['a2a:approve'] : [])] })
    issued.value = result.api_key
    await refresh()
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function revoke(item) {
  if (!window.confirm(`撤销“${item.name || item.key_id}”？该密钥发起的任务将无法继续使用此授权。`)) return
  busy.value = true; error.value = ''
  try { await api.revokeKey(item.key_id); await refresh() }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
onMounted(async () => {
  busy.value = true
  try { await refresh() } catch (e) { error.value = e.message } finally { busy.value = false }
})
</script>

<template>
  <section>
    <header class="page-head"><h1>API 密钥</h1></header>
    <p class="muted">为外部程序绑定一个智能体，并配置接口权限。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form class="panel stack" @submit.prevent="create">
      <fieldset class="stack" :disabled="busy">
        <legend>新建密钥</legend>
        <label class="field"><span>名称</span><input v-model="form.name" maxlength="191" placeholder="例如：自动测试" /></label>
        <label class="field"><span>智能体</span><select v-model="form.agent_id" required>
          <option value="" disabled>请选择智能体</option>
          <option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.name }}</option>
        </select></label>
        <p v-if="!agents.length" class="muted">请先在「智能体」页创建智能体。</p>
        <p class="muted">执行策略继承「执行设置」中的用户配置，同一账号的所有密钥共用。</p>
        <label class="row"><input v-model="form.approve" type="checkbox" />允许此密钥通过 API 批准操作</label>
        <small class="muted">未勾选时，用户可到「待审批」页处理。勾选会授予调用方独立审批权限。</small>
        <button class="btn cta" type="submit" :disabled="!form.agent_id">{{ busy ? '处理中…' : '创建密钥' }}</button>
      </fieldset>
    </form>
    <div v-if="issued" class="panel stack" role="status">
      <strong>密钥只显示这一次，请保存。</strong>
      <textarea :value="issued" readonly rows="3" aria-label="新建的 API 密钥" />
      <button class="btn ghost" type="button" @click="issued = ''">已保存，隐藏密钥</button>
    </div>
    <div class="panel stack" :aria-busy="busy">
      <h2>已创建密钥</h2>
      <p v-if="!keys.length" class="muted">还没有密钥。</p>
      <article v-for="item in keys" :key="item.key_id" class="stack">
        <strong>{{ item.name || item.key_id }} {{ item.revoked_at ? '（已撤销）' : '' }}</strong>
        <p class="muted">{{ item.scopes.includes('a2a:approve') ? '可通过 API 审批' : '由用户审批' }}</p>
        <small class="mono">{{ item.agent_id }}</small>
        <button v-if="!item.revoked_at" class="btn ghost" type="button" :disabled="busy" @click="revoke(item)">撤销</button>
      </article>
    </div>
  </section>
</template>
