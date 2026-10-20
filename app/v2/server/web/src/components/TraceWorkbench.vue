<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api.js'
import { duration, percentage } from '../performance.js'
import { cost, detailTabs, number, pretty, spanTree, waterfall } from '../trace-presentation.js'
import GlassPanel from './GlassPanel.vue'

const props = defineProps({ params: { type: Object, required: true } })
const summary = ref(null), summaryError = ref(''), error = ref(''), loading = ref(false)
const rows = ref([]), cursor = ref(null), kind = ref('AGENT'), status = ref('')
const sessionId = ref(''), sessionInput = ref('')
const dialog = ref(null), traceId = ref(''), spans = ref([]), treeCursor = ref(null)
const treeLoading = ref(false), treeError = ref(''), detailError = ref(''), detailLoading = ref(false)
const selected = ref(''), detail = ref(null), tab = ref('input')
const tree = computed(() => spanTree(spans.value))
const tabs = computed(() => detailTabs(detail.value))
const payload = computed(() => pretty(tabs.value.find(item => item.id === tab.value)?.value))

let pageRevision = 0, summaryRevision = 0, treeRevision = 0, detailRevision = 0
function date(value) { return new Date(value).toLocaleString('zh-CN') }
function tabKey(event, index) {
  let next
  if (event.key === 'ArrowRight') next = (index + 1) % tabs.value.length
  else if (event.key === 'ArrowLeft') next = (index + tabs.value.length - 1) % tabs.value.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = tabs.value.length - 1
  else return
  event.preventDefault(); tab.value = tabs.value[next].id
  event.currentTarget.parentElement.querySelectorAll('[role=tab]')[next].focus()
}
function query() { return { start: props.params.start, end: props.params.end, agent_id: props.params.agent_id || '', ...(sessionId.value ? {session_id:sessionId.value} : {}) } }
function applySession(value = sessionInput.value) {
  sessionInput.value = value.trim()
  if (sessionId.value === sessionInput.value) { loadSummary(); loadPage(); return }
  sessionId.value = sessionInput.value
}
async function loadSummary() {
  const revision = ++summaryRevision
  summary.value = null; summaryError.value = ''
  try { const data = await api.traceSummary(query()); if (revision === summaryRevision) summary.value = data }
  catch (exc) { if (revision === summaryRevision) summaryError.value = exc.message }
}
async function loadPage(more = false) {
  const revision = ++pageRevision
  const params = { ...query(), kind:kind.value, status:status.value }
  if (more && cursor.value) params.cursor = cursor.value
  if (!more) { rows.value = []; cursor.value = null }
  loading.value = true; error.value = ''
  try {
    const data = await api.traceSpans(params)
    if (revision !== pageRevision) return
    rows.value = more ? [...rows.value, ...data.items] : data.items
    cursor.value = data.next_cursor
  } catch (exc) { if (revision === pageRevision) error.value = exc.message }
  finally { if (revision === pageRevision) loading.value = false }
}
function close() {
  ++treeRevision; ++detailRevision; traceId.value = ''; detail.value = null; spans.value = []
  dialog.value?.close()
}
async function select(span) {
  const revision = ++detailRevision
  selected.value = span.span_id; detail.value = null; detailError.value = ''; detailLoading.value = true
  tab.value = span.name === 'sage.diagnostic' ? 'raw' : 'input'
  try {
    const data = await api.traceSpan(span.span_id)
    if (revision === detailRevision) { detail.value = data; tab.value = tabs.value.some(item => item.id === tab.value) ? tab.value : (tabs.value[0]?.id || '') }
  } catch (exc) { if (revision === detailRevision) detailError.value = exc.message }
  finally { if (revision === detailRevision) detailLoading.value = false }
}
async function loadTree(more = false) {
  const revision = ++treeRevision
  treeLoading.value = true; treeError.value = ''
  try {
    const data = await api.traceTree(traceId.value, more ? treeCursor.value : '')
    if (revision !== treeRevision) return
    spans.value = more ? [...spans.value, ...data.items] : data.items
    treeCursor.value = data.next_cursor
  } catch (exc) { if (revision === treeRevision) treeError.value = exc.message }
  finally { if (revision === treeRevision) treeLoading.value = false }
}
async function open(row) {
  close(); traceId.value = row.trace.trace_id; treeCursor.value = null
  await nextTick(); dialog.value.showModal()
  await Promise.all([loadTree(), select(row)])
}
watch(() => props.params, () => { close(); loadSummary(); loadPage() }, { immediate:true })
watch([kind,status], () => loadPage())
watch(sessionId, () => { close(); loadSummary(); loadPage() })
onBeforeUnmount(() => { ++pageRevision; ++summaryRevision; close() })
</script>

<template>
  <section class="trace-workbench" aria-label="模型与调用链">
    <p v-if="summaryError" class="error" role="alert">{{ summaryError }} <button class="btn ghost" @click="loadSummary">重试指标</button></p>
    <div v-if="summary" class="trace-metrics">
      <GlassPanel><h2>总 Token</h2><strong>{{ number(summary.tokens) }}</strong><span>输入 {{ number(summary.input_tokens) }} · 输出 {{ number(summary.output_tokens) }}</span></GlassPanel>
      <GlassPanel><h2>模型成本</h2><strong>{{ cost(summary.cost) }}</strong><span>USD</span></GlassPanel>
      <GlassPanel><h2>错误请求</h2><strong>{{ number(summary.errors) }}</strong><span>共 {{ number(summary.requests) }} 次请求</span></GlassPanel>
      <GlassPanel><h2>请求错误率</h2><strong>{{ percentage(summary.requests ? summary.errors / summary.requests : null) }}</strong></GlassPanel>
    </div>
    <GlassPanel class="trace-list">
      <header><h2>调用链</h2><label>类型<select v-model="kind" aria-label="调用类型"><option value="AGENT">请求</option><option value="LLM">模型</option><option value="TOOL">工具</option><option value="ALL">全部调用</option></select></label><label>状态<select v-model="status"><option value="">全部状态</option><option value="ERROR">错误</option><option value="OK">成功</option><option value="UNSET">未设置</option></select></label></header>
      <form class="session-filter" @submit.prevent="applySession()"><label>Session ID<input v-model="sessionInput" name="session_id" aria-label="session_id" placeholder="输入完整 session_id" maxlength="256" /></label><button class="btn ghost" type="submit">筛选</button><button v-if="sessionId || sessionInput" class="btn ghost" type="button" @click="applySession('')">清除</button></form>
      <p v-if="error" class="error" role="alert">{{ error }} <button class="btn ghost" @click="loadPage()">重试</button></p>
      <p v-if="loading" role="status">加载调用链…</p>
      <p v-if="!loading && !error && !rows.length" class="empty">此时间范围暂无调用链</p>
      <div v-if="rows.length" class="table-scroll"><table><thead><tr><th>开始时间 / 调用</th><th>Session ID</th><th>状态</th><th>耗时</th><th>Token</th><th>成本</th><th>Trace ID</th></tr></thead><tbody>
        <tr v-for="row in rows" :key="row.span_id"><td><button class="trace-open" @click="open(row)"><span>{{ date(row.start_time) }}</span><strong>{{ row.name }}</strong></button></td><td><button v-if="row.session_id" class="trace-id" @click="applySession(row.session_id)">{{ row.session_id }}</button><span v-else>—</span></td><td :class="{'trace-failed': row.status_code === 'ERROR'}">{{ row.status_code }}</td><td>{{ duration(row.latency_ms) }}</td><td>{{ number(row.span_kind === 'AGENT' ? row.cumulative_tokens : row.token_count_total) }}</td><td>{{ cost(row.span_kind === 'AGENT' ? row.trace.cost_summary?.total?.cost : row.cost_summary?.total?.cost) }}</td><td><button class="trace-id" @click="open(row)">{{ row.trace.trace_id }}</button></td></tr>
      </tbody></table></div>
      <button v-if="cursor" class="btn ghost load-more" :disabled="loading" @click="loadPage(true)">加载更多</button>
    </GlassPanel>
    <dialog ref="dialog" class="trace-dialog" aria-labelledby="trace-title" @cancel.prevent="close">
      <header class="trace-dialog-heading"><h2 id="trace-title">调用链详情</h2><code>{{ traceId }}</code><button class="btn ghost" @click="close">关闭</button></header>
      <div class="trace-detail-layout">
        <div class="trace-waterfall">
          <p v-if="treeError" class="error" role="alert">{{ treeError }} <button class="btn ghost" @click="loadTree()">重试</button></p>
          <p v-if="treeLoading" role="status">加载调用记录…</p>
          <p v-if="!treeLoading && !treeError && !tree.length" class="empty">未找到调用记录</p>
          <button v-for="span in tree" :key="span.span_id" class="span-row" :class="{selected: selected === span.span_id, 'trace-failed': span.status_code === 'ERROR'}" :aria-pressed="selected === span.span_id" @click="select(span)">
            <span class="span-name" :style="{paddingLeft: `${12 + Math.min(span.depth,12)*12}px`}"><small>{{ span.span_kind }}</small>{{ span.name }}</span><span class="span-timeline"><i :style="waterfall(spans,span)"></i></span><span>{{ duration(span.latency_ms) }}</span>
          </button>
          <button v-if="treeCursor" class="btn ghost load-more" :disabled="treeLoading" @click="loadTree(true)">加载更多调用记录</button>
        </div>
        <section class="span-inspector" aria-label="调用记录详情">
          <p v-if="detailLoading" role="status">加载完整内容…</p>
          <p v-else-if="detailError" class="error" role="alert">{{ detailError }}</p>
          <template v-else-if="detail">
            <h3>{{ detail.name }} <span :class="{'trace-failed': detail.status_code === 'ERROR'}">{{ detail.status_code }}</span></h3>
            <p v-if="detail.status_message" class="span-status">{{ detail.status_message }}</p>
            <div v-if="tabs.length" class="trace-tabs" role="tablist" aria-label="记录内容"><button v-for="(item,index) in tabs" :id="`trace-tab-${item.id}`" :key="item.id" role="tab" :aria-selected="tab === item.id" :tabindex="tab === item.id ? 0 : -1" aria-controls="trace-payload" @click="tab = item.id" @keydown="tabKey($event,index)">{{ item.name }}</button></div>
            <p v-if="!tabs.length" class="empty">未采集</p><pre v-else id="trace-payload" role="tabpanel" :aria-labelledby="`trace-tab-${tab}`" tabindex="0">{{ payload }}</pre>
          </template>
        </section>
      </div>
    </dialog>
  </section>
</template>

<style scoped>
.trace-workbench { margin-top:18px; }
h2,h3,p { margin:0; } h2 { font-size:14px; font-weight:600; }
.trace-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }
.trace-metrics > * { padding:20px; } .trace-metrics h2,.trace-metrics span { color:var(--muted-foreground); }
.trace-metrics strong { display:block; font-size:27px; font-weight:600; margin:13px 0 7px; font-variant-numeric:tabular-nums; }
.trace-metrics span { font-size:12px; }
.trace-list { margin-top:18px; padding:20px; } header { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.trace-list h2 { margin-right:auto; } label { display:flex; gap:8px; align-items:center; color:var(--muted-foreground); font-size:12px; }
select,input { min-height:36px; border:1px solid var(--border); background:var(--background); color:var(--foreground); border-radius:8px; padding:6px 10px; }
.session-filter { display:flex; align-items:flex-end; gap:10px; flex-wrap:wrap; margin-top:16px; } .session-filter label { flex:1; min-width:160px; } .session-filter input { flex:1; min-width:0; max-width:440px; font:12px monospace; }
.table-scroll { overflow:auto; margin-top:14px; } table { width:100%; border-collapse:collapse; text-align:left; font-size:12px; white-space:nowrap; font-variant-numeric:tabular-nums; }
th,td { padding:12px; border-bottom:1px solid var(--border); } th { color:var(--muted-foreground); font-weight:500; }
.trace-open,.trace-id { color:var(--foreground); cursor:pointer; border:0; background:none; padding:0; text-align:left; }
.trace-open { display:flex; flex-direction:column; gap:6px; } .trace-open span { color:var(--muted-foreground); }
.trace-id { font:11px monospace; color:var(--muted-foreground); } .trace-failed { color:var(--destructive); }
.load-more { display:block; margin:16px auto 0; } .empty { color:var(--muted-foreground); padding:24px 0; }
.error,[role=status] { padding:14px 0; } .error { color:var(--destructive); }
.trace-dialog { padding:0; width:min(1450px,95vw); height:min(850px,90dvh); max-width:95vw; max-height:90dvh; border:1px solid var(--border); border-radius:var(--radius-card,12px); color:var(--foreground); background:var(--card); }
.trace-dialog::backdrop { background:rgb(0 0 0 / .5); }
.trace-dialog-heading { padding:16px 20px; border-bottom:1px solid var(--border); }
.trace-dialog-heading code { color:var(--muted-foreground); font-size:11px; overflow-wrap:anywhere; } .trace-dialog-heading .btn { margin-left:auto; }
.trace-detail-layout { display:grid; grid-template-columns:minmax(300px,45%) minmax(0,1fr); height:calc(100% - 70px); min-height:0; }
.trace-waterfall { overflow:auto; padding:12px; border-right:1px solid var(--border); }
.span-row { width:100%; display:grid; grid-template-columns:minmax(160px,1fr) 100px 65px; align-items:center; gap:8px; padding:10px 6px; border:0; border-bottom:1px solid var(--border); background:transparent; color:var(--foreground); text-align:left; cursor:pointer; font-size:11px; }
.span-row.selected { background:var(--muted); box-shadow:inset 2px 0 var(--accent); } .span-row.trace-failed { color:var(--destructive); }
.span-name { overflow-wrap:anywhere; } .span-name small { display:block; color:var(--muted-foreground); font-size:9px; margin-bottom:4px; }
.span-timeline { position:relative; height:16px; border-left:1px solid var(--border); } .span-timeline i { position:absolute; top:5px; height:6px; min-width:3px; max-width:100%; border-radius:2px; background:var(--accent); }
.span-inspector { min-width:0; overflow:auto; padding:20px; } .span-inspector h3 { font-size:14px; } .span-inspector h3 span { margin-left:10px; font-size:11px; }
.span-status { margin-top:10px; font-size:12px; overflow-wrap:anywhere; }
.trace-tabs { display:flex; gap:4px; flex-wrap:wrap; margin:18px 0 12px; border-bottom:1px solid var(--border); }
.trace-tabs button { padding:9px; color:var(--muted-foreground); background:transparent; border:0; border-bottom:2px solid transparent; cursor:pointer; }
.trace-tabs [aria-selected=true] { color:var(--foreground); border-bottom-color:var(--accent); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.7 monospace; margin:0; padding:12px; background:var(--background); border-radius:8px; tab-size:2; }
button:focus-visible,select:focus-visible,pre:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
@media(max-width:1000px) { .trace-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } .span-row { grid-template-columns:minmax(140px,1fr) 60px; } .span-timeline { display:none; } }
@media(max-width:650px) { .trace-detail-layout { display:flex; flex-direction:column; } .trace-waterfall { max-height:35%; flex-shrink:0; border-right:0; border-bottom:1px solid var(--border); } .span-inspector { flex:1; } .trace-metrics strong { font-size:22px; } .trace-metrics > * { padding:14px; } .trace-dialog-heading code { display:none; } }
</style>
