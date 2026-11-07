<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import { formatBytes } from '../resource-presentation.js'

const props = defineProps({ item: { type: Object, required: true } })
const emit = defineEmits(['changed', 'busy'])
const versions = ref([]), head = ref(props.item.version_id), selected = ref(''), content = ref('')
const loading = ref(false), reading = ref(false), comparing = ref(false), saving = ref(false)
const error = ref(''), message = ref(''), comparison = ref(null), more = ref(false), confirmRollback = ref(false)
const agents = ref([]), agentId = ref(''), binding = ref(null), pin = ref(''), bindingLoading = ref(false)
const readonly = computed(() => isForeign(props.item))
let contentRequest = 0, bindingRequest = 0, alive = true
const selectedVersion = computed(() => versions.value.find(item => item.version_id === selected.value))
const diffLines = delta => delta.split('\n').map(text => ({ text, kind: text.startsWith('+') ? 'added' : text.startsWith('-') ? 'removed' : '' }))
function date(value) { return value ? new Date(value).toLocaleString() : '历史记录' }

async function load(append = false) {
  loading.value = true; error.value = ''
  try {
    const [items, current] = await Promise.all([
      api.skillVersions(props.item.skill_id, props.item._owner, append ? versions.value.at(-1)?.revision : null),
      api.getSkill(props.item.skill_id, props.item._owner),
    ])
    if (!alive) return
    versions.value = append ? [...versions.value, ...items] : items
    head.value = current.version_id; more.value = items.length === 50
    if (!append) await select(head.value)
  } catch (exc) { if (alive) error.value = exc.message }
  finally { if (alive) loading.value = false }
}
async function select(version) {
  const request = ++contentRequest
  selected.value = version; content.value = ''; comparison.value = null; confirmRollback.value = false
  comparing.value = false; reading.value = true; error.value = ''
  try {
    const detail = await api.skillVersion(props.item.skill_id, version, props.item._owner)
    if (alive && request === contentRequest) content.value = detail.content
  } catch (exc) { if (alive && request === contentRequest) error.value = exc.message }
  finally { if (alive && request === contentRequest) reading.value = false }
}
async function compare() {
  const request = contentRequest
  comparing.value = true; error.value = ''
  try {
    const result = await api.skillDiff(props.item.skill_id, selected.value, head.value, props.item._owner)
    if (alive && request === contentRequest) comparison.value = result
  } catch (exc) { if (alive && request === contentRequest) error.value = exc.message }
  finally { if (alive && request === contentRequest) comparing.value = false }
}
async function rollback() {
  if (saving.value || readonly.value) return
  saving.value = true; emit('busy', true); error.value = ''; message.value = ''
  try {
    const result = await api.rollbackSkill(props.item.skill_id, { version_id: selected.value, expected_version_id: head.value })
    if (!alive) return
    confirmRollback.value = false; emit('changed')
    await load()
    if (agentId.value) await loadBinding()
    message.value = `已恢复为修订 ${result.revision}，历史版本仍保留。`
  } catch (exc) { if (alive) error.value = exc.message }
  finally { if (alive) { saving.value = false; emit('busy', false) } }
}
async function loadBinding() {
  const request = ++bindingRequest
  binding.value = null; pin.value = ''; bindingLoading.value = true; error.value = ''; message.value = ''
  try {
    const items = agentId.value ? await api.listAgentSkills(agentId.value) : []
    if (!alive || request !== bindingRequest) return
    binding.value = items.find(item => item.skill_id === props.item.skill_id) || null
    pin.value = binding.value?.version_policy === 'pinned' ? binding.value.version_id : ''
  } catch (exc) { if (alive && request === bindingRequest) error.value = exc.message }
  finally { if (alive && request === bindingRequest) bindingLoading.value = false }
}
async function saveBinding() {
  if (!binding.value || saving.value || readonly.value) return
  saving.value = true; emit('busy', true); error.value = ''; message.value = ''
  try {
    const result = await api.bindSkillVersion(agentId.value, props.item.skill_id, pin.value)
    if (!alive) return
    binding.value = result
    message.value = result.version_policy === 'pinned' ? `已固定到修订 ${result.revision}，对新任务生效。` : '已改为跟随最新版，对新任务生效。'
    emit('changed')
  } catch (exc) { if (alive) error.value = exc.message }
  finally { if (alive) { saving.value = false; emit('busy', false) } }
}
onMounted(async () => {
  await load()
  if (!readonly.value) {
    try { const items = await api.agentSummaries(false); if (alive) agents.value = items }
    catch (exc) { if (alive) error.value = exc.message }
  }
})
onBeforeUnmount(() => { alive = false; contentRequest++; bindingRequest++ })
</script>

<template>
  <section class="skill-versions" aria-label="技能版本" :aria-busy="loading || saving">
    <p class="version-help">回滚会发布新修订并保留历史。跟随最新版的智能体可在下次加载时更新；固定版本保持不变。</p>
    <p v-if="error" class="error" role="alert">{{ error }} <button class="btn ghost" type="button" :disabled="saving" @click="load()">重新加载版本</button></p>
    <p v-if="message" class="version-message" role="status">{{ message }}</p>
    <p v-if="loading && !versions.length" role="status">正在加载版本…</p>
    <div v-if="versions.length" class="version-layout">
      <aside class="version-list" aria-label="版本历史">
        <button v-for="version in versions" :key="version.version_id" class="version-row" type="button" :aria-pressed="selected === version.version_id" :disabled="saving" @click="select(version.version_id)">
          <span><strong>修订 {{ version.revision }}</strong><span v-if="version.version_id === head" class="rs-badge">当前</span></span>
          <time>{{ date(version.created_at) }}</time><small>{{ version.file_count }} 个文件 · {{ formatBytes(version.total_bytes || 0) }}</small>
        </button>
        <button v-if="more" class="btn ghost" type="button" :disabled="loading || saving" @click="load(true)">加载更早版本</button>
      </aside>
      <div class="version-detail">
        <div class="version-actions"><strong>修订 {{ selectedVersion?.revision }}</strong><button class="btn ghost" type="button" :disabled="selected === head || comparing || saving" @click="compare">{{ comparing ? '正在比较…' : '与当前版本比较' }}</button><button v-if="!readonly && selected !== head" class="btn ghost" type="button" :disabled="reading || saving" @click="confirmRollback = true">恢复此版本</button></div>
        <div v-if="confirmRollback" class="rollback-confirm" role="group" aria-label="确认恢复版本"><p>将修订 {{ selectedVersion?.revision }} 的完整文件包恢复为新的当前修订。固定版本的智能体不受影响。</p><button class="btn ghost" type="button" :disabled="saving" @click="confirmRollback = false">取消</button><button class="btn cta" type="button" :disabled="saving" @click="rollback">{{ saving ? '正在恢复…' : '确认恢复' }}</button></div>
        <p v-if="reading" class="version-help" role="status">正在读取版本…</p>
        <template v-else-if="comparison">
          <p class="version-help">从修订 {{ selectedVersion?.revision }} 到当前版本，共 {{ comparison.files.length }} 个文件变化。</p>
          <details v-for="file in comparison.files" :key="file.path" class="version-diff" open><summary>{{ { added: '新增', removed: '删除', modified: '修改' }[file.status] }} · {{ file.path }}</summary><p v-if="file.binary" class="version-help">二进制文件内容发生变化。</p><p v-if="file.truncated" class="version-help">差异较大，未展示完整内容。</p><pre v-if="file.diff"><code><span v-for="(line, index) in diffLines(file.diff)" :key="index" :class="line.kind">{{ line.text }}
</span></code></pre></details>
          <button class="btn ghost" type="button" @click="comparison = null">返回版本说明</button>
        </template>
        <pre v-else class="version-source"><code>{{ content }}</code></pre>
      </div>
    </div>
    <section v-if="!readonly && agents.length" class="version-binding" aria-label="智能体版本策略">
      <h3>智能体版本策略</h3><p class="version-help">策略变更对新任务生效。已有任务保留受理时的策略；工作区在下次加载或手动同步时更新。</p>
      <label>智能体<select v-model="agentId" :disabled="saving" @change="loadBinding"><option value="">选择智能体</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.name }}</option></select></label>
      <p v-if="bindingLoading" role="status">正在读取绑定…</p><p v-else-if="agentId && !binding" class="version-help">此智能体尚未绑定该技能，请先在智能体配置中选择。</p>
      <div v-if="binding && !bindingLoading" class="version-pin"><label>更新方式<select v-model="pin" :disabled="saving"><option value="">跟随最新版</option><option v-if="binding.version_policy === 'pinned' && !versions.some(version => version.version_id === binding.version_id)" :value="binding.version_id">固定修订 {{ binding.revision }}</option><option v-for="version in versions" :key="version.version_id" :value="version.version_id">固定修订 {{ version.revision }}</option></select></label><button class="btn cta" type="button" :disabled="saving" @click="saveBinding">{{ saving ? '正在保存…' : '保存版本策略' }}</button></div>
    </section>
  </section>
</template>

<style scoped>
.skill-versions { min-width: 0; }
.version-help { font-size: 12px; color: var(--muted-foreground); line-height: 1.7; }
.version-message { color: var(--foreground); font-size: 13px; padding: 12px; background: var(--muted); border-radius: 10px; }
.version-layout { display: grid; grid-template-columns: 170px minmax(0, 1fr); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.version-list { max-height: 520px; overflow: auto; border-right: 1px solid var(--border); }
.version-row { display: grid; gap: 6px; width: 100%; padding: 14px; border: 0; border-bottom: 1px solid var(--border); background: transparent; color: var(--foreground); text-align: left; }
.version-row[aria-pressed=true] { background: var(--muted); box-shadow: inset 3px 0 var(--primary); }
.version-row > span { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.version-row time, .version-row small { font-size: 10px; color: var(--muted-foreground); }
.version-row:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.version-detail { min-width: 0; }
.version-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 12px; border-bottom: 1px solid var(--border); font-size: 12px; }
.version-detail > .version-help { padding: 0 14px; }
.version-source, .version-diff pre { margin: 0; padding: 16px; max-height: 420px; overflow: auto; font-size: 12px; line-height: 1.8; }
.version-diff { border-bottom: 1px solid var(--border); }
.version-diff summary { padding: 12px; font-size: 12px; overflow-wrap: anywhere; cursor: pointer; }
.version-diff p { padding: 0 12px; }
.version-diff .added { background: color-mix(in srgb, #16803d 15%, transparent); }
.version-diff .removed { background: color-mix(in srgb, #c62828 15%, transparent); }
.rollback-confirm { padding: 14px; background: var(--muted); font-size: 12px; line-height: 1.7; }
.rollback-confirm .btn + .btn { margin-left: 8px; }
.version-binding { padding-top: 20px; }
.version-binding h3 { font-size: 14px; }
.version-binding label { display: grid; gap: 7px; font-size: 12px; }
.version-binding select { width: 100%; min-height: 38px; background: var(--card); color: var(--foreground); border: 1px solid var(--border); border-radius: 8px; padding: 8px; }
.version-pin { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-top: 12px; }
.version-pin label { flex: 1; min-width: 150px; }
@media (max-width: 600px) { .version-layout { grid-template-columns: 1fr; } .version-list { max-height: 180px; border-right: 0; border-bottom: 1px solid var(--border); } }
</style>
