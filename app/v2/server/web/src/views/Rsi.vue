<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageToolbar from '../components/PageToolbar.vue'
import AppIcon from '../components/AppIcon.vue'
import RsiSetup from '../components/RsiSetup.vue'
import RsiResults from '../components/RsiResults.vue'
import RsiVersionDiff from '../components/RsiVersionDiff.vue'
import { useRsi } from '../use-rsi.js'
import { activeRun, runStatus, runStage, evaluationScore, scoreText } from '../rsi.js'
import { saveDownload } from '../download.js'
import '../rsi.css'

const route = useRoute(), router = useRouter(), state = useRsi(), setupOpen = ref(false)
const { agent, models, runs, run, version, runId, versionId, offset, baseline, applied, conflicted, canApply,
  loading, refreshing, reading, versionLoading, busy, error, readError, actionError, versionError, notice } = state
const definition = computed(() => agent.value?.package?.manifest?.agents?.[agent.value.id])
const unsupported = computed(() => {
  if (!definition.value) return ''
  if (definition.value.mode !== 'simple' || definition.value.entrypoint?.type !== 'loop' || Object.keys(agent.value.package.dependencies || {}).length) return '当前 RSI 支持单个 Simple loop 智能体。'
  if (definition.value.tools?.some(name => name.startsWith('mcp_') || name.startsWith('a2a_'))) return '此智能体包含外部业务工具，需先配置独立测试环境。'
  return ''
})
const selectedEvaluation = computed(() => run.value?.result?.iterations?.find(item => item.iteration === version.value?.iteration)?.evaluation)
const date = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
watch(() => route.params.agentId, id => { setupOpen.value = false; void state.load(id, typeof route.query.run === 'string' ? route.query.run : '') }, { immediate: true })
watch(() => route.query.run, id => { if (typeof id === 'string' && id !== runId.value && !busy.value) void state.selectRun(id) })
watch(runId, id => { if (id && route.query.run !== id) void router.replace({ query: { ...route.query, run: id } }) })
async function start(payload) { if (await state.start(payload)) setupOpen.value = false }
function download() { saveDownload({ blob: new Blob([JSON.stringify(run.value, null, 2)], { type: 'application/json' }), filename: `${runId.value}.json` }) }
function openSetup() { actionError.value = ''; setupOpen.value = true }
</script>

<template>
  <section class="rsi-page" aria-label="RSI 优化">
    <PageToolbar><div class="rsi-title"><RouterLink to="/agents" class="btn ghost" aria-label="返回智能体列表"><AppIcon name="chevron" class="rsi-back" /></RouterLink><h1>{{ agent?.name || '智能体' }} / RSI</h1></div><template #actions><button class="btn ghost" :disabled="refreshing || busy" @click="state.refresh"><AppIcon name="refresh" />刷新</button><button class="btn cta" :disabled="!agent || busy || Boolean(unsupported)" @click="openSetup"><AppIcon name="plus" />新建实验</button></template></PageToolbar>
    <div v-if="loading" class="rsi-panel rsi-loading" aria-busy="true" aria-label="正在加载 RSI"><i v-for="n in 3" :key="n"></i></div>
    <template v-else>
      <p v-if="error" class="rsi-feedback error" role="alert">{{ error }} <button class="btn ghost" :disabled="refreshing || busy" @click="state.refresh">重试</button></p>
      <p v-if="unsupported" class="rsi-feedback" role="status">{{ unsupported }}</p>
      <p v-if="notice" class="rsi-feedback success" role="status">{{ notice }}</p>
      <p v-if="actionError && !setupOpen" class="rsi-feedback error" role="alert">{{ actionError }}</p>
      <div v-if="agent" class="rsi-workspace">
        <aside class="rsi-panel rsi-history" aria-label="实验历史">
          <header class="rsi-section-heading"><h2>实验历史</h2></header>
          <p v-if="!runs.length" class="rsi-feedback">{{ offset ? '没有更多实验' : '还没有实验' }}</p>
          <div class="rsi-history-list"><button v-for="item in runs" :key="item.id" type="button" class="rsi-history-item" :aria-pressed="runId === item.id" :disabled="busy" @click="state.selectRun(item.id)"><span class="rsi-history-top"><strong>{{ item.request?.goal || item.id }}</strong><span class="rsi-badge" :class="activeRun(item) ? 'active' : 'neutral'">{{ runStatus(item) }}</span></span><time :datetime="item.created_at">{{ date(item.created_at) }}</time></button></div>
          <nav v-if="offset || runs.length >= 50" class="rsi-pagination" aria-label="实验历史分页"><button class="btn ghost" :disabled="!offset || busy || refreshing" @click="state.refreshHistory(offset - 50)">上一页</button><span>{{ offset / 50 + 1 }}</span><button class="btn ghost" :disabled="runs.length < 50 || busy || refreshing" @click="state.refreshHistory(offset + 50)">下一页</button></nav>
        </aside>
        <div class="rsi-content">
          <p v-if="readError" class="rsi-feedback error" role="alert">{{ readError }} <button class="btn ghost" :disabled="busy || reading" @click="state.refreshRun">重试读取</button></p>
          <div v-if="reading && !run" class="rsi-panel rsi-loading" aria-busy="true" aria-label="正在读取实验"><i v-for="n in 3" :key="n"></i></div>
          <template v-else-if="run">
            <section class="rsi-panel" aria-label="实验进度">
              <header class="rsi-section-heading"><h2>当前实验</h2><span class="rsi-badge" :class="activeRun(run) ? 'active' : run.status === 'completed' ? 'success' : 'neutral'" role="status" aria-live="polite">{{ runStatus(run) }}</span></header>
              <p class="rsi-goal">{{ run.request.goal }}</p>
              <dl class="rsi-facts"><div><dt>当前阶段</dt><dd>{{ runStage(run) }}</dd></div><div><dt>轮次</dt><dd>{{ run.round ?? run.result?.report?.termination?.completed_rounds ?? 0 }} / {{ run.request.rounds }}</dd></div><div><dt>创建时间</dt><dd>{{ date(run.created_at) }}</dd></div><div><dt>优化范围</dt><dd>{{ run.request.optimization_scope.map(part => ({ instructions: '提示词', skills: '技能' })[part]).join('、') }}</dd></div></dl>
              <p v-if="run.status === 'failed'" class="rsi-feedback error" role="alert">实验未完成：{{ run.error_code || run.error_type || '未知错误' }}</p>
              <div class="rsi-actions"><button v-if="activeRun(run)" class="btn ghost" :disabled="busy" @click="state.control('cancel')">{{ busy ? '处理中…' : '停止实验' }}</button><button v-if="['interrupted', 'failed'].includes(run.status)" class="btn cta" :disabled="busy" @click="state.control('resume')">{{ busy ? '处理中…' : '恢复实验' }}</button><button v-if="run.result" class="btn ghost" @click="download"><AppIcon name="download" />下载结果</button></div>
              <details class="rsi-details"><summary>查看冻结配置</summary><dl class="rsi-facts"><div><dt>训练题量</dt><dd>{{ run.request.initial_training_case_count }}，每轮新增 {{ run.request.training_cases_per_round }}</dd></div><div><dt>验证题量</dt><dd>{{ run.request.validation_case_count }}</dd></div><div><dt>目标得分</dt><dd>{{ scoreText(run.request.stopping_policy?.target_score) }}</dd></div><div><dt>并发 / 每题评测次数</dt><dd>{{ run.request.max_concurrency }} / {{ run.request.evaluation_repeats }}</dd></div><div><dt>模型</dt><dd>{{ models.find(m => m.id === run.request.model_id)?.model || run.request.model_id || '使用默认模型' }}</dd></div><div><dt>实验 ID</dt><dd class="mono">{{ run.id }}</dd></div></dl></details>
            </section>
            <RsiResults v-if="run.result" :result="run.result" />
            <section v-if="run.versions?.length" class="rsi-panel" aria-label="候选版本">
              <header class="rsi-section-heading"><h2>候选版本</h2><span v-if="applied" class="rsi-badge success" role="status">当前已应用</span></header>
              <label class="rsi-field">查看版本<select :value="versionId" :disabled="busy" @change="state.selectVersion($event.target.value)"><option v-for="item in run.versions" :key="item.version_id" :value="item.version_id">{{ item.iteration === 0 ? '基线版本' : `第 ${item.iteration} 轮` }}{{ item.recommended ? ' · 推荐' : item.package_ref === run.candidate_ref ? ' · 保留版本' : '' }}</option></select></label>
              <p v-if="versionLoading" class="rsi-feedback" role="status">正在读取版本…</p>
              <p v-else-if="versionError" class="rsi-feedback error" role="alert">{{ versionError }} <button class="btn ghost" @click="state.selectVersion(versionId)">重试</button></p>
              <template v-else-if="version">
                <dl class="rsi-facts"><div><dt>训练得分</dt><dd>{{ scoreText(evaluationScore(selectedEvaluation, 'training')) }}</dd></div><div><dt>验证得分</dt><dd>{{ scoreText(evaluationScore(selectedEvaluation, 'validation')) }}</dd></div></dl>
                <RsiVersionDiff :baseline="baseline" :candidate="version.package" />
                <p v-if="conflicted" class="rsi-feedback error" role="alert">智能体配置已变更，无法应用此实验候选。请基于最新配置新建实验。</p>
                <div v-if="version.iteration > 0" class="rsi-actions"><button class="btn cta" :disabled="!canApply" @click="state.apply">{{ applied ? '当前已应用' : busy ? '正在处理…' : '应用此版本' }}</button></div>
              </template>
            </section>
          </template>
          <div v-else-if="!reading && !readError" class="rsi-panel rsi-empty"><AppIcon name="agent" /><h2>还没有实验</h2><button class="btn cta" :disabled="busy || Boolean(unsupported)" @click="openSetup">新建实验</button></div>
        </div>
      </div>
    </template>
    <RsiSetup v-model:open="setupOpen" :models="models" :busy="busy" :error="actionError" @start="start" />
  </section>
</template>
