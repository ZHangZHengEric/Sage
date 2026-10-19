<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import ResourceDetails from '../components/ResourceDetails.vue'
import FormDrawer from '../components/FormDrawer.vue'
import AppIcon from '../components/AppIcon.vue'

const drawerOpen = ref(false)

const keys = ref([]), agents = ref([]), busy = ref(false), error = ref(''), issued = ref('')
const ready = ref(false)
const form = ref({ name: '', agent_id: '', approve: false })

async function refresh() {
  const [nextKeys, nextAgents] = await Promise.all([api.listKeys(false), api.listAgents(false)])
  keys.value = nextKeys; agents.value = nextAgents
  ready.value = true
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
async function load() {
  busy.value = true
  try { await refresh() } catch (e) { error.value = e.message } finally { busy.value = false }
}
onMounted(load)
function startNew() {
  error.value = ''; issued.value = ''; form.value = { name: '', agent_id: agents.value[0]?.id || '', approve: false }
  drawerOpen.value = true
}
</script>

<template>
  <section class="api-keys" aria-label="API 密钥">
    <PageToolbar aria-label="密钥操作"><template #actions><button class="btn cta" type="button" :disabled="busy || !ready" @click="startNew"><AppIcon name="plus" />新增密钥</button></template></PageToolbar>
    <div v-if="error && !drawerOpen" class="developer-feedback error" role="alert"><span>{{ error }}</span><button class="btn ghost" :disabled="busy" @click="load">重新加载</button></div>
    <div v-if="busy && !ready" class="developer-skeleton" aria-busy="true" aria-label="正在加载密钥"><i v-for="n in 3" :key="n"></i></div>
    <div v-else-if="ready && !keys.length" class="developer-empty"><AppIcon name="key" /><p>还没有密钥</p><button class="btn cta" :disabled="busy" @click="startNew">新增密钥</button></div>
    <div v-else-if="ready" class="developer-table" :aria-busy="busy">
      <table aria-label="API 密钥列表"><thead><tr><th>名称</th><th>智能体</th><th>审批权限</th><th>状态</th><th>操作</th></tr></thead>
        <tbody><tr v-for="item in keys" :key="`${item._owner?.user_id || ''}:${item.key_id}`">
          <td><strong>{{ item.name || item.key_id }}</strong><small v-if="item._owner" class="developer-meta">{{ item._owner.username }}</small></td>
          <td>{{ agents.find(agent => agent.id === item.agent_id)?.name || item.agent_id }}</td>
          <td>{{ item.scopes.includes('a2a:approve') ? '可通过 API 审批' : '由用户审批' }}</td>
          <td><span class="developer-badge" :class="{ neutral: item.revoked_at }">{{ item.revoked_at ? '已撤销' : '有效' }}</span></td>
          <td><div class="developer-actions"><ResourceDetails :item="item" kind="keys" /><button v-if="!isForeign(item) && !item.revoked_at" class="btn ghost" type="button" :disabled="busy" @click="revoke(item)">撤销</button></div></td>
        </tr></tbody>
      </table>
    </div>
    <FormDrawer v-model="drawerOpen" title="新增密钥" panel-class="developer-drawer" :busy="busy">
      <form id="api-key-form" class="developer-form" @submit.prevent="create">
        <p v-if="error" class="developer-feedback error" role="alert">{{ error }}</p>
        <fieldset class="stack" :disabled="busy || Boolean(issued)">
          <legend class="sr-only">密钥配置</legend>
          <label class="field"><span>名称</span><input v-model="form.name" maxlength="191" placeholder="例如：自动测试" /></label>
          <label class="field"><span>智能体</span><select v-model="form.agent_id" required><option value="" disabled>请选择智能体</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.name }}</option></select></label>
          <p v-if="!agents.length" class="muted">请先在「智能体」页创建智能体。</p>
          <p class="developer-hint">执行策略继承「个人设置 → <router-link to="/settings/execution" @click="drawerOpen = false">执行设置</router-link>」，同一账号的所有密钥共用。</p>
          <label class="developer-checkbox"><input v-model="form.approve" type="checkbox" />允许此密钥通过 API 批准操作</label>
          <p class="developer-hint">未勾选时，用户可在对应会话中处理审批。勾选会授予调用方独立审批权限。</p>
        </fieldset>
      </form>
      <div v-if="issued" class="developer-issued stack" role="status"><strong>密钥只显示这一次，请保存。</strong><textarea :value="issued" readonly rows="3" aria-label="新建的 API 密钥" /><button class="btn ghost" @click="issued = ''; drawerOpen = false">已保存，关闭</button></div>
      <template #footer><div class="developer-actions"><button class="btn ghost" :disabled="busy" @click="drawerOpen = false">关闭</button><button v-if="!issued" class="btn cta" type="submit" form="api-key-form" :disabled="busy || !form.agent_id">{{ busy ? '处理中…' : '创建密钥' }}</button></div></template>
    </FormDrawer>
  </section>
</template>

<style src="../developer-surfaces.css"></style>
