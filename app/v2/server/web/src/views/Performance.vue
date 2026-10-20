<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { duration, percentage, timeRange, chartSegments, purposeLabels } from '../performance.js'
import GlassPanel from '../components/GlassPanel.vue'
import AppIcon from '../components/AppIcon.vue'
import TraceWorkbench from '../components/TraceWorkbench.vue'
const route = useRoute(), router = useRouter()
const period = ref(['1','6','24','168','day','custom'].includes(route.query.period) ? route.query.period : '24')
const day = ref(route.query.day || new Date().toLocaleDateString('en-CA'))
const agent = ref(route.query.agent_id || ''), granularity = ref(route.query.bucket === 'day' ? 'day' : 'hour')
const start = ref(route.query.start || ''), end = ref(route.query.end || '')
const agents = ref([]), result = ref(null), error = ref(''), loading = ref(false), expanded = ref('')
const metric = ref('first_token_ms'), quantile = ref('p95')
const traceParams = ref({})
const metrics = [{ id: 'first_token_ms', name: '端到端首 token' }, { id: 'framework_ms', name: '框架耗时' }, { id: 'total_ms', name: '总耗时' }, { id: 'first_text_ms', name: '首段正文' }]
const summary = computed(() => result.value?.summary)
const chart = computed(() => chartSegments(result.value?.buckets || [], metric.value, quantile.value))
const agentNames = computed(() => Object.fromEntries(agents.value.map(a => [a.agent_id || a.id, `${a.name}${a.username ? ` · ${a.username}` : ''}`])))
const rows = computed(() => result.value?.runs || [])
let revision = 0
function date(value, onlyDate = false) {
  return new Date(value).toLocaleString('zh-CN', onlyDate ? { month:'2-digit',day:'2-digit' } : { month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit' })
}
function bucketLabel(value) { return granularity.value === 'day' ? date(value,true) : new Date(value).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}) }
function name(row) { return agentNames.value[row.agent_id] || row.agent_id || '未知 Agent' }
function status(row) {
  const state = { completed:'已完成', cancelled:'已取消', failed:'失败', suspended:'等待输入', running:'执行中' }[row.state] || row.state
  if (row.state !== 'completed') return state
  if (row.scope !== 'sdk_entry') return `${state} · 初始化未记录`
  if (row.coverage !== 'complete') return `${state} · 采集不完整`
  return state
}
async function load() {
  const current = ++revision
  loading.value = true; error.value = ''
  try {
    const range = period.value === 'custom' ? { start:new Date(start.value).toISOString(), end:new Date(end.value).toISOString() } : timeRange(period.value,day.value)
    const params = { ...range, agent_id:agent.value, bucket:granularity.value, timezone_name:Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai' }
    const response = await api.performance(params)
    if (current !== revision) return
    result.value = response
    traceParams.value = params
    await router.replace({ query:{ period:period.value, day:period.value === 'day' ? day.value : undefined, agent_id:agent.value || undefined, bucket:granularity.value, ...(period.value === 'custom' ? { start:start.value,end:end.value } : {}) } })
  } catch (exc) { if (current === revision) error.value = exc.message }
  finally { if (current === revision) loading.value = false }
}
function rangeChanged() { if (period.value === '168') granularity.value = 'day'; if (period.value !== 'custom') load() }
onMounted(async () => {
  const pending = load()
  try { agents.value = await api.performanceAgents() } catch { /* Timing rows still show stable Agent IDs. */ }
  await pending
})
</script>
<template>
  <div class="performance-page">
    <header class="performance-heading"><h1>运行性能</h1><button class="btn ghost" :disabled="loading" @click="load"><AppIcon name="refresh" />刷新</button></header>
    <GlassPanel as="form" class="performance-filters" @submit.prevent="load">
      <label>时间<select v-model="period" @change="rangeChanged"><option value="1">最近 1 小时</option><option value="6">最近 6 小时</option><option value="24">最近 24 小时</option><option value="168">最近 7 天</option><option value="day">按天</option><option value="custom">自定义</option></select></label>
      <label v-if="period === 'day'">日期<input v-model="day" type="date" required @change="load" /></label>
      <template v-if="period === 'custom'"><label>开始<input v-model="start" type="datetime-local" required /></label><label>结束<input v-model="end" type="datetime-local" required /></label></template>
      <label>Agent<select v-model="agent" @change="load"><option value="">全部 Agent</option><option v-for="item in agents" :key="`${item.user_id}:${item.agent_id || item.id}`" :value="item.agent_id || item.id">{{ item.name }}{{ item.username ? ` · ${item.username}` : '' }}</option></select></label>
      <label>粒度<select v-model="granularity" @change="load"><option value="hour">每小时</option><option value="day">每天</option></select></label>
      <button v-if="period === 'custom'" type="submit" class="btn cta" :disabled="loading">查询</button>
    </GlassPanel>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">加载中…</p>
    <template v-if="summary">
      <div class="performance-counts"><span>{{ summary.requests }} 次请求</span><span>{{ summary.measured }} 次完整采样</span><span v-if="summary.incomplete" class="quality-warning">{{ summary.incomplete }} 次缺少完整计时</span><span v-if="result.capture_failures" class="quality-warning">采集丢失 {{ result.capture_failures }}</span><span v-if="result.truncated" class="quality-warning">达到采样上限，请缩小时间范围</span></div>
      <div class="performance-cards"><GlassPanel v-for="item in metrics" :key="item.id" class="performance-card"><h2>{{ item.name }}</h2><strong>{{ duration(summary[item.id]?.p50) }}</strong><div class="quantiles"><span>P50</span><span>P95 {{ duration(summary[item.id]?.p95) }}</span></div><span v-if="item.id === 'framework_ms'" class="ratio">占比 {{ percentage(summary.framework_ratio) }}</span></GlassPanel></div>
      <GlassPanel class="performance-chart">
        <div class="chart-controls"><h2>耗时趋势</h2><select v-model="metric" aria-label="趋势指标"><option v-for="item in metrics" :key="item.id" :value="item.id">{{ item.name }}</option></select><select v-model="quantile" aria-label="分位数"><option value="p50">P50</option><option value="p95">P95</option></select></div>
        <div class="plot"><p v-if="!chart.points.length" class="empty">暂无完整采样</p><span v-else class="plot-maximum">{{ duration(chart.maximum) }}</span><svg viewBox="0 0 900 180" role="img" :aria-label="`${metrics.find(m => m.id === metric)?.name} ${quantile}趋势`"><path d="M16 160H884M16 90H884M16 20H884" class="plot-grid" /><polyline v-for="(segment,i) in chart.segments" :key="i" :points="segment" class="plot-line" /><circle v-for="(point,i) in chart.points" :key="`p${i}`" :cx="point[0]" :cy="point[1]" r="3" class="plot-dot" /></svg><div class="plot-range"><span>{{ result.buckets[0] ? date(result.buckets[0].time) : '' }}</span><span>{{ result.buckets.length ? date(result.buckets.at(-1).time) : '' }}</span></div></div>
        <div class="table-scroll bucket-table"><table><thead><tr><th>时间</th><th>完整采样</th><th>首 token P95</th><th>总耗时 P95</th><th>框架 P95</th><th>框架占比</th></tr></thead><tbody><tr v-for="b in result.buckets" :key="b.time"><td>{{ bucketLabel(b.time) }}</td><td>{{ b.measured }}</td><td>{{ duration(b.first_token_ms.p95) }}</td><td>{{ duration(b.total_ms.p95) }}</td><td>{{ duration(b.framework_ms.p95) }}</td><td>{{ percentage(b.framework_ratio) }}</td></tr></tbody></table></div>
      </GlassPanel>
      <TraceWorkbench v-if="result.source === 'phoenix'" :params="traceParams" />
      <GlassPanel class="performance-runs"><h2>请求回合</h2><p v-if="!rows.length" class="empty">此时间范围暂无记录</p><div v-else class="table-scroll"><table><thead><tr><th>开始时间 / Agent</th><th>首 token</th><th>首段正文</th><th>总耗时</th><th>LLM</th><th>工具</th><th>框架</th><th>记录</th></tr></thead><tbody><template v-for="row in rows" :key="row.run_id"><tr><td><button class="run-toggle" :aria-expanded="expanded === row.run_id" @click="expanded = expanded === row.run_id ? '' : row.run_id"><span>{{ date(row.started_at) }}</span><span>{{ name(row) }}</span></button></td><td>{{ duration(row.first_token_ms) }}</td><td>{{ duration(row.first_text_ms) }}</td><td>{{ duration(row.total_ms) }}</td><td>{{ duration(row.model_ms) }}</td><td>{{ duration(row.tool_ms) }}</td><td>{{ duration(row.framework_ms) }}</td><td><span :class="{ 'quality-warning': row.coverage !== 'complete' }">{{ status(row) }}</span></td></tr><tr v-if="expanded === row.run_id"><td colspan="8"><div class="run-details"><span>{{ row.run_id }}</span><span>{{ row.session_id }}</span><span>模型首 token {{ duration(row.model_ttft_ms) }}</span><span>模型调用 {{ row.model_calls }} 次</span><span>工具执行 {{ row.tool_calls }} 次</span><span>模型与工具并行 {{ duration(row.overlap_ms) }}</span><span>暂停等待 {{ duration(row.waiting_ms) }}</span><span v-for="(value,key) in row.purposes" :key="key">{{ purposeLabels[key] || key }} {{ value.calls }} 次 · {{ duration(value.ms) }}</span></div></td></tr></template></tbody></table></div><p v-if="result.run_list_truncated" class="quality-warning">显示最近 200 次，汇总包含 {{ result.total_runs }} 次。</p></GlassPanel>
    </template>
  </div>
</template>
<style scoped>
.performance-page { max-width: 1440px; margin: 0 auto; padding: 28px; color: var(--foreground); }
.performance-heading, .chart-controls, .performance-counts { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.performance-heading { justify-content: space-between; margin-bottom: 22px; }
h1 { font-size: 23px; margin: 0; } h2 { font-size: 14px; margin: 0; font-weight: 600; }
.performance-heading .btn { display: inline-flex; align-items: center; gap: 7px; }
.performance-filters { display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; padding: 18px; }
label { display: flex; flex-direction: column; gap: 7px; font-size: 12px; color: var(--muted-foreground); }
select, input { min-height: 38px; border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; color: var(--foreground); background: var(--background); font: inherit; max-width: 100%; }
select { cursor: pointer; } button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.performance-counts { font-size: 12px; margin: 18px 0; color: var(--muted-foreground); }
.quality-warning { color: var(--status-warning); }
.performance-cards { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; }
.performance-card { padding: 20px; position: relative; } .performance-card h2 { color: var(--muted-foreground); }
.performance-card strong { display: block; margin: 13px 0 7px; font-size: 29px; font-weight: 600; font-variant-numeric: tabular-nums; }
.quantiles { display: flex; gap: 14px; font-size: 12px; color: var(--muted-foreground); } .ratio { display: block; font-size: 12px; margin-top: 9px; }
.performance-chart, .performance-runs { padding: 20px; margin-top: 18px; } .chart-controls h2 { margin-right: auto; }
.plot { margin-top: 15px; } .plot svg { display: block; width: 100%; height: 180px; } .plot-grid { stroke: var(--border); fill: none; stroke-dasharray: 3 5; }
.plot-line { fill: none; stroke: var(--accent); stroke-width: 2; } .plot-dot { fill: var(--accent); } .plot-range { display: flex; justify-content: space-between; }
.plot-range, .plot-maximum { color: var(--muted-foreground); font-size: 11px; }
.table-scroll { overflow: auto; margin-top: 16px; } .bucket-table { max-height: 220px; } table { border-collapse: collapse; width: 100%; text-align: left; font-size: 12px; white-space: nowrap; font-variant-numeric: tabular-nums; }
th, td { padding: 11px 12px; border-bottom: 1px solid var(--border); } th { color: var(--muted-foreground); font-weight: 500; }
.run-toggle { display: flex; flex-direction: column; gap: 4px; border: 0; background: transparent; color: var(--foreground); cursor: pointer; text-align: left; padding: 0; }
.run-toggle span:last-child { color: var(--muted-foreground); max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.run-details { display: flex; gap: 12px 22px; flex-wrap: wrap; white-space: normal; padding: 8px 0; color: var(--muted-foreground); } .run-details span { overflow-wrap: anywhere; }
.empty { color: var(--muted-foreground); padding: 30px 0; }
@media(max-width:1000px) { .performance-cards { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media(max-width:600px) { .performance-page { padding: 18px 12px; } .performance-filters { padding: 14px; gap: 12px; } label { flex: 1 1 130px; min-width: 0; } .performance-card { padding: 14px; } .performance-card strong { font-size: 24px; } .performance-chart, .performance-runs { padding: 14px; } .quantiles { flex-wrap: wrap; gap: 6px; } }
</style>
