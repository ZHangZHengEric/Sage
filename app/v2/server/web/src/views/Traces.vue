<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { timeRange } from '../performance.js'
import GlassPanel from '../components/GlassPanel.vue'
import AppIcon from '../components/AppIcon.vue'
import TraceWorkbench from '../components/TraceWorkbench.vue'

const route = useRoute(), router = useRouter()
const period = ref(['1','6','24','168','day','custom'].includes(route.query.period) ? route.query.period : '24')
const day = ref(route.query.day || new Date().toLocaleDateString('en-CA'))
const agent = ref(route.query.agent_id || '')
const start = ref(route.query.start || ''), end = ref(route.query.end || '')
const agents = ref([]), params = ref(null), error = ref('')
async function load() {
  error.value = ''
  try {
    const range = period.value === 'custom' ? { start:new Date(start.value).toISOString(), end:new Date(end.value).toISOString() } : timeRange(period.value, day.value)
    if (new Date(range.start) >= new Date(range.end)) throw Error('结束时间必须晚于开始时间')
    params.value = { ...range, agent_id:agent.value }
    await router.replace({ query:{ period:period.value, day:period.value === 'day' ? day.value : undefined, agent_id:agent.value || undefined, ...(period.value === 'custom' ? {start:start.value,end:end.value} : {}) } })
  } catch (exc) { error.value = exc.message }
}
function rangeChanged() { if (period.value !== 'custom') load() }
onMounted(async () => {
  load()
  try { agents.value = await api.performanceAgents() } catch { /* Agent filtering is optional. */ }
})
</script>
<template>
  <div class="traces-page">
    <header class="traces-heading"><h1>调用链</h1><button class="btn ghost" @click="load"><AppIcon name="refresh" />刷新</button></header>
    <GlassPanel as="form" class="trace-filters" @submit.prevent="load">
      <label>时间<select v-model="period" @change="rangeChanged"><option value="1">最近 1 小时</option><option value="6">最近 6 小时</option><option value="24">最近 24 小时</option><option value="168">最近 7 天</option><option value="day">按天</option><option value="custom">自定义</option></select></label>
      <label v-if="period === 'day'">日期<input v-model="day" type="date" required @change="load" /></label>
      <template v-if="period === 'custom'"><label>开始<input v-model="start" type="datetime-local" required /></label><label>结束<input v-model="end" type="datetime-local" required /></label></template>
      <label>Agent<select v-model="agent" @change="load"><option value="">全部 Agent</option><option v-for="item in agents" :key="`${item.user_id}:${item.agent_id || item.id}`" :value="item.agent_id || item.id">{{ item.name }}{{ item.username ? ` · ${item.username}` : '' }}</option></select></label>
      <button v-if="period === 'custom'" type="submit" class="btn cta" >查询</button>
    </GlassPanel>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <TraceWorkbench v-if="params" :params="params" />
  </div>
</template>
<style scoped>
.traces-page { max-width: 1440px; margin: 0 auto; padding: 28px; color: var(--foreground); }
.traces-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 22px; }
h1 { font-size: 23px; margin: 0; }
.trace-filters { display: flex; align-items: end; flex-wrap: wrap; gap: 16px; padding: 18px; }
label { display: flex; flex-direction: column; gap: 7px; font-size: 12px; color: var(--muted-foreground); }
select, input { border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; background: var(--background); color: var(--foreground); font: inherit; }
.error { color: var(--danger); }
@media(max-width:600px) { .traces-page { padding: 18px 12px; } .trace-filters { padding: 14px; gap: 12px; } label { flex: 1 1 130px; min-width: 0; } }
</style>
