<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, isForeign } from '../api.js'
import FormDrawer from '../components/FormDrawer.vue'
import PackageEditor from '../components/PackageEditor.vue'
import PageToolbar from '../components/PageToolbar.vue'
import AppIcon from '../components/AppIcon.vue'

const tab = ref('versions'), ready = ref(false)
const definitionOpen = ref(false), runOpen = ref(false), legacyContinuation = ref(false)
import { onBeforeRouteLeave, useRouter } from 'vue-router'
const router = useRouter()

const resources = ref({})
const packages = ref([]), runs = ref([]), agents = ref([]), schema = ref(null)
const editor = ref(''), savedRef = ref(''), savedText = ref(''), selectedAgent = ref('assistant')
const content = ref(''), sessionId = ref(''), operation = ref(''), status = ref(null)
const events = ref([]), eventCursor = ref(0)
const bundleOwner = ref(null), runOwner = ref(null)
const foreignBundle = computed(() => isForeign({ _owner: bundleOwner.value }))
const foreignRun = computed(() => isForeign({ _owner: runOwner.value }))
const decision = ref(''), reply = ref('{}'), error = ref(''), message = ref(''), busy = ref(false)
const importId = ref(''), forkId = ref(''), forkVersion = ref('1.0.0'), offset = ref(0), runOffset = ref(0)
let timer, disposed = false, statusRevision = 0, polling = false
const answer = computed(() => (status.value?.result?.final_items || []).flatMap(item => item.data?.content || item.content || []).map(block => block.text || '').filter(Boolean).join('\n'))
const clean = computed(() => savedRef.value && editor.value === savedText.value)
const definitions = computed(() => { try { return Object.keys(JSON.parse(editor.value).manifest.agents) } catch { return [] } })
function setBundle(bundle, reference = '', owner = null) {
  legacyContinuation.value = false
  bundleOwner.value = owner; runOwner.value = null
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
async function startNew() { if (canReplaceDraft()) await action(async () => { const [bundle, available] = await Promise.all([api.packageTemplate(), api.packageResources()]); resources.value = available; setBundle(bundle); definitionOpen.value = true }) }
async function importDraft() { if (canReplaceDraft()) await action(async () => setBundle(await api.packageTemplate(importId.value))) }
async function load(row) { if (canReplaceDraft()) await action(async () => { setBundle(await api.package(row.ref, row._owner), row.ref, row._owner); if (!isForeign(row)) resources.value = await api.packageResources(); definitionOpen.value = true }) }
async function inspect(op, owner = runOwner.value) {
  const revision = ++statusRevision
  const result = await api.packageRun(op, owner)
  if (!disposed && revision === statusRevision) {
    if (operation.value !== op || runOwner.value?.user_id !== owner?.user_id) { events.value = []; eventCursor.value = 0 }
    operation.value = op; runOwner.value = owner; status.value = result
    const page = await api.packageEvents(op, eventCursor.value, owner)
    if (!disposed && revision === statusRevision) {
      events.value = [...events.value, ...page.events]; eventCursor.value = page.cursor
    }
  }
}
async function continueConversation() {
  await action(async () => {
    const previous = status.value
    const bundle = await api.package(previous.ref)
    setBundle(bundle, previous.ref)
    selectedAgent.value = previous.agent_id || runs.value.find(r => r.operation === previous.operation)?.agent || selectedAgent.value
    legacyContinuation.value = true
    sessionId.value = previous.run.session_id
    runOpen.value = true
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
  await action(async () => { const result = await api.savePackage(JSON.parse(editor.value)); savedRef.value = result.ref; savedText.value = editor.value; message.value = '版本已保存'; await refresh(); definitionOpen.value = false })
}
async function run() {
  await action(async () => {
    if (legacyContinuation.value) {
      const id = `${Date.now()}-${crypto.randomUUID()}`
      await api.runPackage({ ref: savedRef.value, agent_id: selectedAgent.value, content: content.value, operation: id, session_id: sessionId.value })
      await inspect(id, null); await refresh(); runOpen.value = false
      return
    }
    const key = `sage.package-run.${crypto.randomUUID()}`
    sessionStorage.setItem(key, JSON.stringify({ content: content.value }))
    await router.push({ path: '/', query: { package: savedRef.value, packageAgent: selectedAgent.value,
      draft: key, ...(sessionId.value ? { thread: sessionId.value } : {}) } })
  })
}
async function activate(row) {
  await action(async () => {
    // Every row carries the active pointer captured with that inventory page.
    await api.activatePackage(row.ref, row.active_ref || null); await refresh(); message.value = '活动版本已切换'
  })
}
onMounted(() => action(async () => {
  const [s, a, bundle] = await Promise.all([api.packageSchema(), api.listAgents(false), api.packageTemplate()])
  if (disposed) return
  schema.value = s; agents.value = a; setBundle(bundle); await refresh(); ready.value = true
  timer = setInterval(async () => {
    if (polling || busy.value || !operation.value || status.value?.terminal || status.value?.needs_attention) return
    polling = true
    try { await inspect(operation.value) } catch (e) { error.value = e.message; clearInterval(timer) } finally { polling = false }
  }, 2000)
}))
onUnmounted(() => { disposed = true; statusRevision++; clearInterval(timer) })
</script>

<template>
  <section class="studio" aria-label="Studio">
    <PageToolbar aria-label="Studio 操作">
      <nav class="source-tabs" aria-label="Studio 分类"><button :aria-pressed="tab === 'versions'" @click="tab = 'versions'">版本库</button><button :aria-pressed="tab === 'runs'" @click="tab = 'runs'">运行记录</button></nav>
      <template #actions><button v-if="tab === 'versions'" class="btn cta" :disabled="busy || !ready" @click="startNew"><AppIcon name="plus" />新增定义</button><button v-else class="btn cta" :disabled="busy || !clean || foreignBundle" @click="runOpen = true"><AppIcon name="plus" />新增任务</button></template>
    </PageToolbar>
    <p role="alert" v-if="error && !definitionOpen && !runOpen" class="developer-feedback error">{{ error }}</p><p v-if="message && !definitionOpen && !runOpen" role="status" class="developer-feedback">{{ message }}</p>
    <div v-if="busy && !ready" class="developer-skeleton" aria-busy="true" aria-label="正在加载 Studio"><i v-for="n in 3" :key="n"></i></div>
    <div v-else-if="!ready && error" class="developer-empty"><p>暂时无法加载 Studio</p><button class="btn ghost" @click="router.go(0)">重新加载</button></div>
    <template v-else-if="ready && tab === 'versions'">
      <div v-if="!packages.length" class="developer-empty"><AppIcon name="code" /><p>{{ offset ? '没有更多版本' : '还没有保存的版本' }}</p><button v-if="!offset" class="btn cta" :disabled="busy" @click="startNew">新增定义</button></div>
      <div v-else class="developer-table" :aria-busy="busy"><table aria-label="版本库"><thead><tr><th>定义</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>
        <tr v-for="p in packages" :key="`${p._owner?.user_id || ''}:${p.ref}`"><td><strong>{{ p.package }}</strong><small v-if="p._owner" class="developer-meta">{{ p._owner.username }}</small></td><td class="mono">{{ p.version }}</td><td><span class="developer-badge" :class="{ neutral: !p.active }">{{ p.active ? '活动版本' : '已保存' }}</span></td><td><div class="developer-actions"><button class="btn ghost" :disabled="busy" @click="load(p)">打开</button><button v-if="!isForeign(p)" class="btn ghost" :disabled="busy || p.active" @click="activate(p)">切换到此版本</button></div></td></tr>
      </tbody></table></div>
      <nav v-if="offset || packages.length >= 50" class="developer-pagination" aria-label="版本分页"><button class="btn ghost" :disabled="busy || offset === 0" @click="action(async () => { offset -= 50; await refresh() })">上一页</button><span>第 {{ offset / 50 + 1 }} 页</span><button class="btn ghost" :disabled="busy || packages.length < 50" @click="action(async () => { offset += 50; await refresh() })">下一页</button></nav>
    </template>
    <template v-else-if="ready">
      <div v-if="!runs.length" class="developer-empty"><AppIcon name="history" /><p>{{ runOffset ? '没有更多运行记录' : '还没有运行记录' }}</p></div>
      <div v-else class="developer-table" :aria-busy="busy"><table aria-label="运行记录"><thead><tr><th>任务</th><th>入口 Agent</th><th>操作</th></tr></thead><tbody><tr v-for="r in runs" :key="`${r._owner?.user_id || ''}:${r.operation}`"><td class="mono">{{ r.operation }}<small v-if="r._owner" class="developer-meta">{{ r._owner.username }}</small></td><td>{{ r.agent }}</td><td><button class="btn ghost" :disabled="busy" @click="action(() => inspect(r.operation, r._owner))">查看</button></td></tr></tbody></table></div>
      <nav v-if="runOffset || runs.length >= 50" class="developer-pagination" aria-label="运行记录分页"><button class="btn ghost" :disabled="busy || runOffset === 0" @click="action(async () => { runOffset -= 50; await refresh() })">上一页</button><span>第 {{ runOffset / 50 + 1 }} 页</span><button class="btn ghost" :disabled="busy || runs.length < 50" @click="action(async () => { runOffset += 50; await refresh() })">下一页</button></nav>
      <fieldset v-if="operation" class="studio-detail" :disabled="busy" aria-label="运行详情">
        <div class="developer-actions"><button class="btn ghost" @click="action(() => inspect(operation))">刷新状态</button><button class="btn ghost" :disabled="foreignRun || status?.terminal" @click="control('cancel')">取消任务</button><button class="btn ghost" :disabled="foreignRun || !status?.terminal" @click="continueConversation">继续此会话</button></div>
        <div v-if="status?.needs_attention && !foreignRun" class="developer-form stack"><p>{{ status.interaction.payload?.prompt }}</p><label class="field">决策<select v-model="decision"><option value="" disabled>请选择</option><option v-for="choice in status.interaction.allowed_decisions" :key="choice" :value="choice">{{ choice }}</option></select></label><label class="field">回复 payload（JSON）<textarea v-model="reply" /></label><div class="developer-actions"><button class="btn cta" @click="control('reply')">提交反馈并恢复</button><button class="btn ghost" @click="control('approve')">提交人工审批决定</button></div></div>
        <p>状态：<span class="developer-badge">{{ status?.run?.state || status?.state }}</span></p>
        <pre v-if="answer" aria-label="回答">{{ answer }}</pre><pre v-if="status?.flow_results">{{ JSON.stringify(status.flow_results, null, 2) }}</pre>
        <details><summary>执行事件</summary><ol><li v-for="event in events" :key="event.event_id"><details><summary>{{ event.run_sequence }} · {{ event.type }}</summary><pre>{{ JSON.stringify(event, null, 2) }}</pre></details></li></ol><button class="btn ghost" @click="action(() => inspect(operation))">加载后续事件</button></details>
        <details><summary>运行详情</summary><pre aria-label="运行结果">{{ JSON.stringify(status, null, 2) }}</pre></details>
      </fieldset>
    </template>
    <FormDrawer v-model="definitionOpen" title="定义与版本" panel-class="developer-drawer studio-drawer" :busy="busy" wide>
      <PackageEditor v-if="foreignBundle" :model-value="editor" :schema="schema" disabled />
      <fieldset v-else :disabled="busy" class="developer-form">
        <p v-if="error" class="developer-feedback error" role="alert">{{ error }}</p><p v-if="message" class="developer-feedback" role="status">{{ message }}</p>
        <div class="row"><label class="field">导入现有 Agent<select v-model="importId"><option value="">空白模板</option><option v-for="a in agents" :key="a.id" :value="a.id">{{ a.name }}</option></select></label><button class="btn ghost" @click="importDraft">导入为草稿</button></div>
        <PackageEditor v-model="editor" :saved-value="savedText" :schema="schema" :resources="resources" :disabled="busy" />
        <details><summary>宿主能力与完整 Schema</summary><pre>{{ JSON.stringify(schema, null, 2) }}</pre></details>
        <div class="studio-fork"><label class="field">复制为新包<input v-model="forkId" placeholder="新包 ID" /></label><label class="field">新版本<input v-model="forkVersion" /></label><button class="btn ghost" :disabled="!clean || !forkId" @click="action(async () => { const r = await api.forkPackage(savedRef, forkId, forkVersion); setBundle(await api.package(r.ref), r.ref); await refresh() })">复制已保存版本</button></div>
      </fieldset>
      <template v-if="!foreignBundle" #footer><div class="developer-actions"><button class="btn ghost" :disabled="busy" @click="action(async () => { const r = await api.validatePackage(JSON.parse(editor)); message = r.valid ? (r.readiness?.ready ? '配置验证通过，资源已就绪' : '配置验证通过') : '配置验证未通过' })">验证与资源检查</button><button class="btn cta" :disabled="busy" @click="save">保存版本</button></div></template>
    </FormDrawer>
    <FormDrawer v-model="runOpen" title="新增任务" panel-class="developer-drawer studio-drawer" :busy="busy">
      <form id="studio-run-form" @submit.prevent="run"><fieldset :disabled="busy || foreignBundle" class="developer-form stack"><p v-if="error" class="developer-feedback error" role="alert">{{ error }}</p><label class="field">入口 Agent<select v-model="selectedAgent"><option v-for="id in definitions" :key="id">{{ id }}</option></select></label><label class="field">任务<textarea v-model="content" rows="3" /></label><label class="field">续接 Session（留空新建）<input v-model="sessionId" /></label><p v-if="!clean" class="developer-hint">运行前请先保存当前定义。</p></fieldset></form>
      <template #footer><div class="developer-actions"><button class="btn cta" type="submit" form="studio-run-form" :disabled="busy || foreignBundle || !clean || !content.trim()">运行已保存版本</button></div></template>
    </FormDrawer>
  </section>
</template>

<style src="../developer-surfaces.css"></style>
