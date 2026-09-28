<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'
import { onBeforeRouteLeave } from 'vue-router'

const packages = ref([]), runs = ref([]), agents = ref([]), schema = ref(null)
const editor = ref(''), savedRef = ref(''), savedText = ref(''), selectedAgent = ref('assistant')
const content = ref(''), sessionId = ref(''), operation = ref(''), status = ref(null)
const events = ref([]), eventCursor = ref(0)
const decision = ref(''), reply = ref('{}'), error = ref(''), message = ref(''), busy = ref(false)
const importId = ref(''), forkId = ref(''), forkVersion = ref('1.0.0'), offset = ref(0), runOffset = ref(0)
let timer, disposed = false, statusRevision = 0, polling = false
const answer = computed(() => (status.value?.result?.final_items || []).flatMap(item => item.data?.content || item.content || []).map(block => block.text || '').filter(Boolean).join('\n'))
const clean = computed(() => savedRef.value && editor.value === savedText.value)
const definitions = computed(() => { try { return Object.keys(JSON.parse(editor.value).manifest.agents) } catch { return [] } })
function setBundle(bundle, reference = '') {
  editor.value = JSON.stringify(bundle, null, 2); savedText.value = editor.value; savedRef.value = reference
  selectedAgent.value = bundle.manifest.entrypoint.agent || Object.keys(bundle.manifest.agents)[0]
  sessionId.value = ''; status.value = null; operation.value = ''; events.value = []; eventCursor.value = 0; statusRevision++
}
async function action(work) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await work() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function refresh() {
  const [p, r] = await Promise.all([api.packages(offset.value), api.packageRuns(runOffset.value)])
  if (!disposed) { packages.value = p; runs.value = r }
}
function canReplaceDraft() { return editor.value === savedText.value || window.confirm('当前修改尚未保存，确定放弃吗？') }
onBeforeRouteLeave(() => canReplaceDraft())
async function importDraft() { if (canReplaceDraft()) await action(async () => setBundle(await api.packageTemplate(importId.value))) }
async function load(reference) { if (canReplaceDraft()) await action(async () => setBundle(await api.package(reference), reference)) }
async function inspect(op) {
  const revision = ++statusRevision
  const result = await api.packageRun(op)
  if (!disposed && revision === statusRevision) {
    if (operation.value !== op) { events.value = []; eventCursor.value = 0 }
    operation.value = op; status.value = result
    const page = await api.packageEvents(op, eventCursor.value)
    if (!disposed && revision === statusRevision) {
      events.value = [...events.value, ...page.events].slice(-100); eventCursor.value = page.cursor
    }
  }
}
async function continueConversation() {
  await action(async () => {
    const previous = status.value
    const bundle = await api.package(previous.ref)
    setBundle(bundle, previous.ref)
    selectedAgent.value = previous.agent_id || runs.value.find(r => r.operation === previous.operation)?.agent || selectedAgent.value
    sessionId.value = previous.run.session_id
    content.value = ''; message.value = '已选择原版本和会话，请输入下一轮任务。'
  })
}
async function control(kind) {
  await action(async () => {
    await api.controlPackageRun(operation.value, { action: kind, decision: decision.value,
      interaction_id: status.value?.interaction?.interaction_id, payload: JSON.parse(reply.value) })
    await inspect(operation.value)
  })
}
async function save() {
  await action(async () => { const result = await api.savePackage(JSON.parse(editor.value)); savedRef.value = result.ref; savedText.value = editor.value; message.value = '版本已保存'; await refresh() })
}
async function run() {
  await action(async () => {
    const id = `${Date.now()}-${crypto.randomUUID()}`
    await api.runPackage({ ref: savedRef.value, agent_id: selectedAgent.value, content: content.value, operation: id, session_id: sessionId.value || null })
    await inspect(id); await refresh()
  })
}
async function activate(row) {
  await action(async () => {
    // Every row carries the active pointer captured with that inventory page.
    await api.activatePackage(row.ref, row.active_ref || null); await refresh(); message.value = '活动版本已切换'
  })
}
onMounted(() => action(async () => {
  const [s, a, bundle] = await Promise.all([api.packageSchema(), api.listAgents(), api.packageTemplate()])
  if (disposed) return
  schema.value = s; agents.value = a; setBundle(bundle); await refresh()
  timer = setInterval(async () => {
    if (polling || busy.value || !operation.value || status.value?.terminal || status.value?.needs_attention) return
    polling = true
    try { await inspect(operation.value) } catch (e) { error.value = e.message; clearInterval(timer) } finally { polling = false }
  }, 2000)
}))
onUnmounted(() => { disposed = true; statusRevision++; clearInterval(timer) })
</script>

<template>
  <section class="studio">
    <h1>Agent Studio</h1>
    <p>编辑完整定义，保存不可变版本，再运行和处理多轮反馈。模型填写当前用户的模型 ID；默认模型用 default。</p>
    <p role="alert" v-if="error" class="error">{{ error }}</p><p role="status">{{ message }}</p>
    <fieldset :disabled="busy">
      <legend>定义与版本</legend>
      <label>导入现有 Agent <select v-model="importId"><option value="">空白模板</option><option v-for="a in agents" :key="a.id" :value="a.id">{{ a.name }}</option></select></label>
      <button @click="importDraft">导入为草稿</button>
      <label class="editor">完整包定义<textarea aria-label="完整包定义" v-model="editor" spellcheck="false" rows="22" /></label>
      <button @click="action(async () => { const r = await api.validatePackage(JSON.parse(editor)); message = JSON.stringify(r, null, 2) })">验证与资源检查</button>
      <button @click="save">保存版本</button>
      <details><summary>宿主能力与完整 Schema</summary><pre>{{ JSON.stringify(schema, null, 2) }}</pre></details>
      <h2>版本库</h2>
      <ul><li v-for="p in packages" :key="p.ref">{{ p.package }} · {{ p.version }} {{ p.active ? '（活动）' : '' }} <button @click="load(p.ref)">打开</button><button @click="activate(p)">切换到此版本</button></li></ul>
      <button :disabled="offset === 0" @click="action(async () => { offset -= 50; await refresh() })">上一页</button>
      <button :disabled="packages.length < 50" @click="action(async () => { offset += 50; await refresh() })">下一页</button>
      <label>复制为新包 <input v-model="forkId" placeholder="新包 ID" /></label><input aria-label="新版本" v-model="forkVersion" />
      <button :disabled="!clean || !forkId" @click="action(async () => { const r = await api.forkPackage(savedRef, forkId, forkVersion); setBundle(await api.package(r.ref), r.ref); await refresh() })">复制已保存版本</button>
    </fieldset>
    <fieldset :disabled="busy">
      <legend>运行与多轮反馈</legend>
      <label>入口 Agent <select v-model="selectedAgent"><option v-for="id in definitions" :key="id">{{ id }}</option></select></label>
      <label>任务<textarea v-model="content" rows="3" /></label>
      <label>续接 Session（留空新建）<input v-model="sessionId" /></label>
      <button :disabled="!clean || !content.trim()" @click="run">运行已保存版本</button>
      <p v-if="!clean">运行前请先保存当前定义。</p>
      <h2>任务历史</h2><ul><li v-for="r in runs" :key="r.operation"><button @click="action(() => inspect(r.operation))">{{ r.operation }} · {{ r.agent }}</button></li></ul>
      <button :disabled="runOffset === 0" @click="action(async () => { runOffset -= 50; await refresh() })">上一页任务</button>
      <button :disabled="runs.length < 50" @click="action(async () => { runOffset += 50; await refresh() })">下一页任务</button>
      <template v-if="operation">
        <button @click="action(() => inspect(operation))">刷新状态</button><button :disabled="status?.terminal" @click="control('cancel')">取消任务</button><button :disabled="!status?.terminal" @click="continueConversation">继续此会话</button>
        <div v-if="status?.needs_attention"><p>{{ status.interaction.payload?.prompt }}</p><label>决策<select v-model="decision"><option value="" disabled>请选择</option><option v-for="choice in status.interaction.allowed_decisions" :key="choice" :value="choice">{{ choice }}</option></select></label><label>回复 payload（JSON）<textarea v-model="reply" /></label><button @click="control('reply')">提交反馈并恢复</button><button @click="control('approve')">提交人工审批决定</button></div>
        <details><summary>最近执行事件（最多 100 条）</summary><ol><li v-for="event in events" :key="event.event_id">{{ event.run_sequence }} · {{ event.type }}</li></ol></details>
        <p>状态：{{ status?.run?.state || status?.state }}</p>
        <pre v-if="answer" aria-label="回答">{{ answer }}</pre>
        <pre v-if="status?.flow_results">{{ JSON.stringify(status.flow_results, null, 2) }}</pre>
        <details><summary>运行详情</summary><pre aria-label="运行结果">{{ JSON.stringify(status, null, 2) }}</pre></details>
      </template>
    </fieldset>
  </section>
</template>

<style scoped>
.studio { max-width: 1100px; margin: auto; padding: 24px; }
fieldset { border: 1px solid #8885; border-radius: 12px; margin: 20px 0; padding: 20px; min-width: 0; }
label { display: block; margin: 12px 0; } textarea { width: 100%; box-sizing: border-box; }
.editor textarea, pre { font-family: monospace; } pre { overflow: auto; max-height: 500px; white-space: pre-wrap; overflow-wrap: anywhere; }
button, input, select { margin: 5px; padding: 7px 12px; } button { border: 1px solid #8885; border-radius: 8px; cursor: pointer; background: #f6f6f6; } button:disabled { cursor: default; opacity: .5; } .error { color: #c44; }
</style>
