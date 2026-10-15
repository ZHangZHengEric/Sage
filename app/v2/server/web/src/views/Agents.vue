<script setup>
import { computed, onMounted, ref } from 'vue'
import { getUser } from '../auth.js'
import { api, isForeign } from '../api.js'
import AgentEditor from '../components/AgentEditor.vue'
import AppIcon from '../components/AppIcon.vue'

const drawerOpen = ref(false)
const viewOnly = ref(false), selectedAgent = ref(null), selectedSkills = ref([]), savedMessage = ref('')
const viewModels = ref([]), viewSkills = ref([]), viewExternalTools = ref([])
const editorModels = computed(() => viewOnly.value ? viewModels.value : models.value)
const editorSkills = computed(() => viewOnly.value ? viewSkills.value : skills.value)
const editorExternalTools = computed(() => viewOnly.value ? viewExternalTools.value : externalTools.value)
const loading = ref(true)

const agents = ref([])
const models = ref([])
const mcp = ref([])
const peers = ref([])
const skills = ref([])
const officialTools = ref([])
const error = ref('')
const pending = ref(false)
const editing = ref('')
const form = ref(emptyForm())

const hasAgents = computed(() => agents.value.length > 0)
// External Tools are granted per catalog rather than per Agent: they only
// exist once the server or peer has been asked, so nothing here could name
// them ahead of time. Shown, not offered.
const externalTools = computed(() => [
  ...new Set([
    ...mcp.value.flatMap((item) => item.tools || []),
    ...peers.value.flatMap((item) => (item.disabled ? [] : item.skills || [])),
  ]),
])
function emptyForm() {
  return {
    name: '',
    description: '',
    instructions: 'Be helpful, concise, and explicit about uncertainty.',
    model_id: '',
    budgets: {},
    tools: [],
    sandbox: { network: 'none' },
    tool_approval: { default: 'auto_approve', tools: {} },
    execution_policy: { shell: 'sandboxed', on_approval_required: 'suspend', approval_timeout_seconds: 86400 },
  }
}

async function refresh() {
  const [nextAgents, nextModels, nextMcp, nextPeers, nextSkills, nextTools] =
    await Promise.all([
      api.listAgents(),
      api.listModels(false),
      api.listMcp(false),
      api.listA2aAgents(false),
      api.listSkills(false),
      api.listTools(),
    ])
  agents.value = nextAgents
  models.value = nextModels
  mcp.value = nextMcp
  peers.value = nextPeers
  skills.value = nextSkills.filter(item => !item.owner_user_id || item.owner_user_id === getUser()?.user_id)
  officialTools.value = nextTools
}

async function save(exit = true) {
  if (viewOnly.value || isForeign(selectedAgent.value) || pending.value) return
  error.value = ''
  savedMessage.value = ''
  pending.value = true
  try {
    const payload = { ...form.value }
    const saved = editing.value
      ? await api.updateAgent(editing.value, payload)
      : await api.createAgent(payload)
    editing.value = saved.id
    selectedAgent.value = saved
    await api.bindAgentSkills(saved.id, selectedSkills.value)
    await refresh()
    savedMessage.value = '已保存'
    if (exit) drawerOpen.value = false
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

async function openAgent(item, readonly = true) {
  error.value = ''; savedMessage.value = ''; pending.value = true
  try {
    const [detail, assigned] = await Promise.all([
      api.getAgent(item.id, item._owner), api.listAgentSkills(item.id, item._owner),
    ])
    selectedAgent.value = item
    viewOnly.value = readonly || isForeign(item)
    editing.value = item.id
    form.value = {
      name: detail.name, description: detail.description || '', instructions: detail.instructions || '',
      budgets: structuredClone(detail.package?.manifest?.agents?.[item.id]?.budgets || {}),
      model_id: detail.model_id || '', tools: [...(detail.tools || [])],
      tool_approval: detail.tool_approval ? structuredClone(detail.tool_approval) : null,
      execution_policy: { ...(detail.execution_policy || emptyForm().execution_policy) },
      sandbox: { ...(detail.sandbox || emptyForm().sandbox) },
    }
    selectedSkills.value = assigned.map(skill => skill.name)
    viewModels.value = isForeign(item) ? [] : models.value
    viewSkills.value = isForeign(item) ? assigned : skills.value
    viewExternalTools.value = isForeign(item) ? [] : externalTools.value
    drawerOpen.value = true
  } catch (exc) { error.value = exc.message }
  finally { pending.value = false }
}
function edit(item) { return openAgent(item, false) }
function enableEdit() { if (!isForeign(selectedAgent.value)) viewOnly.value = false }

function startNew() {
  viewOnly.value = false; selectedAgent.value = null; selectedSkills.value = []; savedMessage.value = ''
  drawerOpen.value = true
  error.value = ''
  editing.value = ''
  form.value = emptyForm()
}

async function remove(id) {
  await api.deleteAgent(id)
  if (editing.value === id) startNew()
  await refresh()
}

onMounted(async () => {
  try {
    await refresh()
  } catch (exc) {
    error.value = exc.message
  } finally { loading.value = false }
})
</script>

<template>
  <section class="agents-page" :class="{ 'editing-agent': drawerOpen }">
    <template v-if="!drawerOpen">
    <header class="page-head">
      <h1>智能体</h1>
      <div class="page-actions">
        <button class="btn cta" :disabled="pending" @click="startNew"><AppIcon name="plus" /> 创建智能体</button>
      </div>
    </header>
    <p v-if="error && !drawerOpen" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="page-loading" role="status">加载中…</p>
    <p v-else-if="!hasAgents" class="empty">还没有智能体</p>
    <div v-else class="panel table-panel">
      <table>
        <thead><tr><th>ID</th><th>智能体</th><th>模型</th><th>工具 / 技能</th><th v-if="agents[0]?._owner">用户</th><th>操作</th></tr></thead>
        <tbody><tr v-for="item in agents" :key="`${item._owner?.user_id || ''}:${item.id}`">
          <td class="agent-id">{{ item.id }}</td>
          <td><button class="agent-name" :disabled="pending" @click="openAgent(item)">{{ item.name }}</button><div v-if="item.description" class="muted">{{ item.description }}</div></td>
          <td class="agent-model">{{ (!isForeign(item) && models.find(model => model.id === item.model_id)?.model) || item.model_id || '默认' }}</td>
          <td class="muted">{{ item.tools?.length || 0 }} 工具 · {{ item.skills?.length || 0 }} 技能</td>
          <td v-if="agents[0]?._owner">{{ item._owner?.username }}</td>
          <td class="row"><button class="btn ghost" :disabled="pending" @click="openAgent(item)">查看</button><button v-if="!isForeign(item)" class="btn ghost" @click="edit(item)">编辑</button><button v-if="!isForeign(item)" class="btn ghost" @click="remove(item.id)">删除</button></td>
        </tr></tbody>
      </table>
    </div>
    </template>
    <AgentEditor v-else v-model:form="form" v-model:selected-skills="selectedSkills"
      :agent-id="editing" :readonly="viewOnly" :can-edit="!isForeign(selectedAgent)" :busy="pending"
      :error="error" :message="savedMessage" :models="editorModels" :tools="officialTools.filter(tool => tool.source !== 'mcp')" :approval-tools="officialTools"
      :skills="editorSkills" :external-tools="editorExternalTools"
      @save="save" @edit="enableEdit" @close="drawerOpen = false" />
  </section>
</template>
<style scoped>
.agents-page.editing-agent { height: 100%; max-width: none; margin: 0; }
.agent-name { font: inherit; text-align: left; color: inherit; border: 0; background: none; padding: 0; overflow-wrap: anywhere; }
.agent-name:hover { text-decoration: underline; text-underline-offset: 3px; }
.agent-id { font-size: 12px; color: var(--muted-foreground); overflow-wrap: anywhere; user-select: text; }
.agent-model { white-space: nowrap; }
</style>
