<script setup>
import PageToolbar from '../components/PageToolbar.vue'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getUser } from '../auth.js'
import { api, isForeign } from '../api.js'
import AgentEditor from '../components/AgentEditor.vue'
import AppIcon from '../components/AppIcon.vue'
import FormDrawer from '../components/FormDrawer.vue'
import { cloneConfiguration, sameConfiguration } from '../agent-presentation.js'
import { useRouter } from 'vue-router'

const router = useRouter()
function openRsi() {
  if (!editing.value || isForeign(selectedAgent.value) || pending.value || syncingSkills.value) return
  if (!sameConfiguration(form.value, savedForm.value) || !sameConfiguration(selectedSkills.value, savedSkills.value)) {
    error.value = '请先保存配置，再打开 RSI'; return
  }
  void router.push(`/agents/${encodeURIComponent(editing.value)}/rsi`)
}

const drawerOpen = ref(false)
const viewOnly = ref(false), selectedAgent = ref(null), selectedSkills = ref([]), savedMessage = ref('')
let savedMessageTimer
function clearSavedMessage() {
  clearTimeout(savedMessageTimer)
  savedMessageTimer = undefined
  savedMessage.value = ''
}
function notifySuccess(message) {
  clearSavedMessage()
  savedMessage.value = message
  savedMessageTimer = setTimeout(clearSavedMessage, 3000)
}
onUnmounted(clearSavedMessage)
const loading = ref(true)

const agents = ref([])
const memberAgents = computed(() => agents.value.filter(item => item.id !== editing.value &&
  (selectedAgent.value?._owner ? item._owner?.user_id === selectedAgent.value._owner.user_id : !isForeign(item))))
const models = ref([])
const skills = ref([])
const officialTools = ref([])
const error = ref('')
const pending = ref(false)
const syncingSkills = ref(false)
const editing = ref('')
const form = ref(emptyForm())
const savedPlugins = ref({}), savedForm = ref(null), savedSkills = ref([])
const budgetDefaults = ref({})
const search = ref(''), ownerFilter = ref('all'), deleteOpen = ref(false), deleteTarget = ref(null), deleteError = ref('')
const visibleAgents = computed(() => {
  const query = search.value.trim().toLowerCase()
  return agents.value.filter(item => (ownerFilter.value === 'all' || (ownerFilter.value === 'own' ? !isForeign(item) : isForeign(item))) && (!query || [item.name, item.description, item.id, item.model_name, item.model_id, item._owner?.username].join(' ').toLowerCase().includes(query)))
})
const pluginCatalog = ref(null)
const resourceRequests = new Map()
const resourcesLoading = ref(false), resourcesError = ref('')
const approvalLoading = ref(false), approvalError = ref('')
const externalTools = ref([]), externalToolGroups = ref([])
let editorSequence = 0, approvalRequest = null

function emptyForm() {
  return {
    name: '',
    description: '',
    instructions: 'Be helpful, concise, and explicit about uncertainty.',
    model_id: '', fast_model_id: '',
    agent_mode: 'simple', available_sub_agent_ids: [],
    budgets: {},
    memory: { recall: true, auto_write: true, scope: 'agent' },
    plugins: {},
    tools: officialTools.value.filter(tool => tool.default).map(tool => tool.name),
    external_tools: [],
    sandbox: { network: 'none' },
    tool_approval: { default: 'auto_approve', tools: {} },
    execution_policy: { shell: 'sandboxed', on_approval_required: 'suspend', approval_timeout_seconds: 86400 },
  }
}

async function refresh() {
  agents.value = await api.agentSummaries()
}

function loadEditorResources(owner) {
  const key = owner?.user_id || getUser()?.user_id || ''
  if (!resourceRequests.has(key)) {
    const request = api.agentEditorResources(owner, !pluginCatalog.value).catch(exc => {
      if (resourceRequests.get(key) === request) resourceRequests.delete(key)
      throw exc
    })
    resourceRequests.set(key, request)
  }
  return resourceRequests.get(key)
}
function applyResources(data) {
  if (data.plugins) pluginCatalog.value = data.plugins
  models.value = data.models
  skills.value = data.skills
  officialTools.value = data.tools
  externalTools.value = data.external_tools
  externalToolGroups.value = data.external_tool_groups || []
  const configurable = new Set(pluginCatalog.value?.configurable || [])
  const plugins = Object.fromEntries(Object.entries(form.value.plugins || {}).filter(([key]) => configurable.has(key)))
  form.value = { ...form.value, plugins }
  savedPlugins.value = cloneConfiguration(plugins)
  if (savedForm.value) savedForm.value = { ...savedForm.value, plugins: cloneConfiguration(plugins) }
}
async function finishResources(result, sequence) {
  if (sequence !== editorSequence) return
  resourcesLoading.value = false
  if (result.error) resourcesError.value = result.error.message
  else applyResources(result.data)
}
async function retryResources() {
  if (resourcesLoading.value) return
  const sequence = editorSequence
  resourcesLoading.value = true; resourcesError.value = ''
  const result = await loadEditorResources(selectedAgent.value?._owner).then(data => ({ data }), error => ({ error }))
  await finishResources(result, sequence)
}
async function loadApprovalTools() {
  if (approvalRequest || resourcesLoading.value || resourcesError.value) return
  const sequence = editorSequence
  approvalLoading.value = true; approvalError.value = ''
  const request = api.agentApprovalTools(selectedAgent.value?._owner)
  approvalRequest = request
  try {
    const tools = await request
    if (sequence === editorSequence) officialTools.value = tools
  } catch (exc) {
    if (sequence === editorSequence) { approvalError.value = exc.message; approvalRequest = null }
  } finally { if (sequence === editorSequence) approvalLoading.value = false }
}
function closeEditor() { editorSequence++; drawerOpen.value = false; resourcesLoading.value = false; error.value = ''; clearSavedMessage() }

async function syncSkills() {
  if (!editing.value || viewOnly.value || isForeign(selectedAgent.value) || pending.value || syncingSkills.value) return
  if (!sameConfiguration(form.value, savedForm.value) || !sameConfiguration(selectedSkills.value, savedSkills.value)) return
  const sequence = editorSequence
  syncingSkills.value = true; error.value = ''; clearSavedMessage()
  try {
    const result = await api.syncAgentSkills(editing.value)
    if (sequence !== editorSequence) return
    if (result.failed_count) {
      const failures = result.results.filter(item => !item.success).map(item => `${item.name}：${item.message}`).join('；')
      error.value = `技能同步成功 ${result.success_count} 个，失败 ${result.failed_count} 个：${failures}`
    } else if (result.results.length && !result.results.some(item => item.workspaces)) {
      notifySuccess('当前暂无已创建的工作区，技能将在首次加载时写入')
    } else {
      notifySuccess(`Agent 技能同步完成：${result.success_count} 个技能`)
    }
  } catch (exc) {
    if (sequence === editorSequence) error.value = exc.message
  } finally { syncingSkills.value = false }
}

async function save(exit = true) {
  if (viewOnly.value || isForeign(selectedAgent.value) || pending.value || syncingSkills.value || resourcesLoading.value || resourcesError.value) return
  error.value = ''
  clearSavedMessage()
  pending.value = true
  try {
    const payload = cloneConfiguration(form.value)
    const skillNames = [...selectedSkills.value]
    const saved = editing.value
      ? await api.updateAgent(editing.value, payload)
      : await api.createAgent(payload)
    editing.value = saved.id
    selectedAgent.value = saved
    await api.bindAgentSkills(saved.id, skillNames)
    savedForm.value = cloneConfiguration(payload)
    savedSkills.value = skillNames
    savedPlugins.value = cloneConfiguration(payload.plugins || {})
    if (exit) closeEditor()
    notifySuccess('已保存')
    try { await refresh() } catch (exc) { error.value = `配置已保存，但列表刷新失败：${exc.message}` }
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
  }
}

async function openAgent(item, readonly = true) {
  if (pending.value) return
  error.value = ''; clearSavedMessage(); pending.value = true
  try {
    const sequence = ++editorSequence
    resourcesLoading.value = true; resourcesError.value = ''; approvalError.value = ''
    approvalRequest = null; approvalLoading.value = false
    models.value = []; skills.value = []; officialTools.value = []; externalTools.value = []; externalToolGroups.value = []
    const resources = loadEditorResources(item._owner).then(data => ({ data }), error => ({ error }))
    const detail = await api.getAgent(item.id, item._owner)
    selectedAgent.value = item
    viewOnly.value = readonly || isForeign(item)
    editing.value = item.id
    budgetDefaults.value = cloneConfiguration({ budgets: detail.package?.manifest?.policies?.budgets || {}, entrypoint: detail.package?.manifest?.agents?.[item.id]?.entrypoint || {} })
    form.value = {
      name: detail.name, description: detail.description || '', instructions: detail.instructions || '',
      plugins: cloneConfiguration(detail.package?.manifest?.runtime?.capabilities || {}),
      budgets: structuredClone(detail.package?.manifest?.agents?.[item.id]?.budgets || {}),
      memory: structuredClone(detail.package?.manifest?.agents?.[item.id]?.memory || { recall: false, auto_write: false, scope: 'agent' }),
      model_id: detail.model_id || '', fast_model_id: detail.fast_model_id || '', tools: [...(detail.tools || [])],
      agent_mode: detail.agent_mode || 'simple', available_sub_agent_ids: [...(detail.available_sub_agent_ids || [])],
      external_tools: [...(detail.external_tools || [])],
      tool_approval: detail.tool_approval ? structuredClone(detail.tool_approval) : null,
      execution_policy: { ...(detail.execution_policy || emptyForm().execution_policy) },
      sandbox: { ...(detail.sandbox || emptyForm().sandbox) },
    }
    selectedSkills.value = [...(detail.skills || [])]
    savedPlugins.value = cloneConfiguration(form.value.plugins)
    savedForm.value = cloneConfiguration(form.value)
    savedSkills.value = [...selectedSkills.value]
    drawerOpen.value = true
    void resources.then(result => finishResources(result, sequence))
  } catch (exc) { error.value = exc.message; resourcesLoading.value = false; editorSequence++ }
  finally { pending.value = false }
}
function edit(item) { return openAgent(item, false) }
function enableEdit() { if (!isForeign(selectedAgent.value)) viewOnly.value = false }

async function startNew() {
  if (pending.value) return
  clearSavedMessage()
  pending.value = true
  error.value = ''
  try {
    editorSequence++
    applyResources(await loadEditorResources())
    resourcesLoading.value = false; resourcesError.value = ''
    approvalRequest = null; approvalError.value = ''; approvalLoading.value = false
    viewOnly.value = false; selectedAgent.value = null; selectedSkills.value = []
    editing.value = ''
    form.value = emptyForm()
    budgetDefaults.value = {}
    savedPlugins.value = {}
    savedForm.value = cloneConfiguration(form.value)
    savedSkills.value = []
    drawerOpen.value = true
  } catch (exc) { error.value = exc.message }
  finally { pending.value = false }
}

function requestDelete(item) {
  if (!item?.id || pending.value || isForeign(item)) return
  deleteTarget.value = item; deleteError.value = ''; deleteOpen.value = true
}
async function remove(item) {
  if (!item?.id || isForeign(item) || pending.value) return
  pending.value = true; deleteError.value = ''
  try {
    await api.deleteAgent(item.id)
    if (editing.value === item.id) { drawerOpen.value = false; editing.value = ''; selectedAgent.value = null }
    deleteOpen.value = false; deleteTarget.value = null; notifySuccess('智能体已删除')
    try { await refresh() } catch (exc) { error.value = `智能体已删除，但列表刷新失败：${exc.message}` }
  } catch (exc) { deleteError.value = exc.message }
  finally { pending.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try { await refresh() } catch (exc) { error.value = exc.message }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <section aria-label="智能体" class="agents-page" :class="{ 'editing-agent': drawerOpen }">
    <template v-if="!drawerOpen">
      <PageToolbar aria-label="智能体操作"><template v-if="agents.length"><div class="agent-list-filters" aria-label="智能体筛选"><button v-for="[value, label] in [['all', '全部智能体'], ['own', '我的'], ['foreign', '其他用户']]" :key="value" type="button" :aria-pressed="ownerFilter === value" @click="ownerFilter = value">{{ label }}</button></div></template><template #actions><template v-if="agents.length"><label class="agent-search"><AppIcon name="search" /><input v-model="search" type="search" aria-label="搜索智能体" placeholder="搜索名称、用途或 ID" /></label></template><button class="agent-action primary" type="button" :disabled="pending || loading" @click="startNew"><AppIcon name="plus" />创建智能体</button></template></PageToolbar>
      <p v-if="savedMessage" class="agent-feedback success" role="status"><AppIcon name="check" />{{ savedMessage }}</p>
      <p v-if="error && agents.length" class="agent-feedback error" role="alert">{{ error }}<button class="agent-action" type="button" :disabled="pending || loading" @click="load">重新加载</button></p>
      <div v-if="loading" class="agent-card-grid" aria-busy="true" aria-label="正在加载智能体"><div v-for="n in 3" :key="n" class="agent-card-skeleton"><i></i><i></i><i></i></div></div>
      <div v-else-if="error && !agents.length" class="agent-list-empty" role="alert"><AppIcon name="alert" /><h2>暂时无法加载智能体</h2><p>{{ error }}</p><button class="agent-action primary" type="button" @click="load">重新加载</button></div>
      <div v-else-if="!agents.length" class="agent-list-empty"><AppIcon name="agent" /><h2>创建你的第一个智能体</h2><button class="agent-action primary" type="button" :disabled="pending" @click="startNew"><AppIcon name="plus" />创建智能体</button></div>
      <div v-else-if="!visibleAgents.length" class="agent-list-empty"><AppIcon name="search" /><h2>没有找到匹配的智能体</h2><button class="agent-action" type="button" @click="search = ''; ownerFilter = 'all'">清除筛选</button></div>
      <div v-else class="agent-card-grid">
        <article v-for="(item, index) in visibleAgents" :key="`${item._owner?.user_id || ''}:${item.id}`" class="agent-summary-card">
          <header><span class="agent-avatar" :data-tone="index % 4" aria-hidden="true">{{ Array.from(item.name || '智能体')[0] }}</span><div class="agent-card-title"><h2>{{ item.name }}</h2><code>{{ item.id }}</code></div><span v-if="isForeign(item)" class="agent-badge">只读</span></header>
          <p v-if="item.description" class="agent-card-description">{{ item.description }}</p>
          <div class="agent-card-model"><AppIcon name="model" />{{ item.model_name || item.model_id || '使用默认模型' }}</div>
          <footer><span class="agent-card-resources"><span><AppIcon name="tools" />{{ item.tool_count ?? '—' }} 工具</span><span><AppIcon name="skill" />{{ item.skill_count ?? '—' }} 技能</span><span v-if="item._owner" class="agent-card-owner">{{ item._owner.username }}</span></span><div class="rsi-card-actions"><RouterLink v-if="!isForeign(item)" class="agent-action subtle" :to="`/agents/${encodeURIComponent(item.id)}/rsi`" :aria-label="`RSI 优化 ${item.name}`">RSI</RouterLink><button class="agent-action subtle" type="button" :disabled="pending" :aria-label="`${isForeign(item) ? '查看' : '配置'} ${item.name}`" @click="openAgent(item, isForeign(item))">{{ isForeign(item) ? '查看' : '配置' }}<AppIcon name="chevron" /></button></div></footer>
        </article>
      </div>
    </template>
    <AgentEditor v-else v-model:form="form" v-model:selected-skills="selectedSkills"
      :agent-id="editing" :readonly="viewOnly" :can-edit="!isForeign(selectedAgent)" :busy="pending" :syncing-skills="syncingSkills"
      :error="error" :message="savedMessage" :models="models" :tools="officialTools.filter(tool => tool.source !== 'mcp')" :approval-tools="officialTools"
      :skills="skills" :member-agents="memberAgents" :external-tools="externalTools" :external-tool-groups="externalToolGroups" :saved-plugins="savedPlugins" :plugin-catalog="pluginCatalog"
      :resources-loading="resourcesLoading" :resources-error="resourcesError" :approval-loading="approvalLoading" :approval-error="approvalError"
      :saved-form="savedForm" :saved-skills="savedSkills" :budget-defaults="budgetDefaults" :can-delete="Boolean(editing && !isForeign(selectedAgent))"
      @save="save" @rsi="openRsi" @sync-skills="syncSkills" @edit="enableEdit" @close="closeEditor" @reload-resources="retryResources" @load-approval-tools="loadApprovalTools" @delete="requestDelete(selectedAgent)" />
    <FormDrawer v-model="deleteOpen" centered panel-class="agent-confirm-dialog" title="删除智能体" :busy="pending">
      <p class="agent-confirm-copy">确认删除「{{ deleteTarget?.name }}」？此操作无法在页面中撤销。</p><p v-if="deleteError" class="error" role="alert">{{ deleteError }}</p><div class="agent-confirm-actions"><button class="agent-action" type="button" :disabled="pending" @click="deleteOpen = false">取消</button><button class="agent-action danger" type="button" :disabled="pending" @click="remove(deleteTarget)">{{ pending ? '正在删除…' : '确认删除' }}</button></div>
    </FormDrawer>
  </section>
</template>

<style scoped>
.rsi-card-actions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.rsi-card-actions a { text-decoration: none; }
</style>
