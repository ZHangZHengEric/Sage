<script setup>
import { computed } from 'vue'
import { evaluationScore, scoreText } from '../rsi.js'
const props = defineProps({ result: Object })
const report = computed(() => props.result?.report)
const metrics = computed(() => [['training', '训练集'], ['validation', '验证集']].map(([split, label]) => ({ label,
  before: evaluationScore(report.value?.baseline, split), after: evaluationScore(report.value?.selected, split) })))
const ending = computed(() => ({ target_reached: '达到目标并完成稳定复测', stagnation: '连续多轮未改善', round_limit: '达到轮数上限' }[report.value?.termination?.reason] || '实验已结束'))
</script>

<template>
  <section v-if="report" class="rsi-panel" aria-label="实验结果">
    <header class="rsi-section-heading"><h2>评测结果</h2><span class="rsi-badge" :class="report.goal_verified ? 'success' : 'neutral'">{{ report.goal_verified ? '已达标' : report.improved ? '有改善，尚未达标' : '尚未改善' }}</span></header>
    <div class="rsi-table-wrap"><table class="rsi-table" aria-label="基线与保留版本评分"><thead><tr><th>分组</th><th>基线</th><th>保留版本</th><th>变化</th></tr></thead><tbody><tr v-for="m in metrics" :key="m.label"><th>{{ m.label }}</th><td>{{ scoreText(m.before) }}</td><td>{{ scoreText(m.after) }}</td><td>{{ m.before != null && m.after != null ? `${m.after - m.before >= 0 ? '+' : ''}${(m.after - m.before).toFixed(3)}` : '—' }}</td></tr></tbody></table></div>
    <dl class="rsi-facts"><div><dt>结束原因</dt><dd>{{ ending }}</dd></div><div><dt>已完成轮数</dt><dd>{{ report.termination?.completed_rounds ?? report.rounds.length }}</dd></div></dl>
    <details v-if="report.rounds.length" class="rsi-details"><summary>每轮结果（{{ report.rounds.length }}）</summary><div class="rsi-table-wrap"><table class="rsi-table" aria-label="每轮选版结果"><thead><tr><th>轮次</th><th>验证得分</th><th>选版</th><th>依据</th></tr></thead><tbody><tr v-for="round in report.rounds" :key="round.round"><td>{{ round.round }}</td><td>{{ scoreText(evaluationScore(round.evaluation, 'validation')) }}</td><td>{{ round.accepted ? '已保留' : '未保留' }}</td><td class="rsi-reason">{{ round.reason }}</td></tr></tbody></table></div></details>
    <details class="rsi-details"><summary>保留版本逐题结果（{{ report.selected.cases.length }}）</summary>
      <details v-for="row in report.selected.cases" :key="`${row.case.split}:${row.case.id}`" class="rsi-case">
        <summary><span class="rsi-badge neutral">{{ row.case.split === 'validation' ? '验证' : '训练' }}</span><span>{{ row.case.id }}</span><span>{{ scoreText(row.grade?.score) }} · {{ row.grade?.passed ? '通过' : '未通过' }}</span></summary>
        <dl class="rsi-case-content"><dt>任务</dt><dd>{{ row.case.input }}</dd><dt>评分标准</dt><dd>{{ row.case.rubric }}</dd><dt>实际回答</dt><dd><pre class="rsi-answer">{{ row.observation?.output || '无文本回答' }}</pre></dd><dt>评测依据</dt><dd>{{ row.grade?.rationale }}</dd><template v-if="row.grade?.diagnosis?.summary"><dt>诊断</dt><dd>{{ row.grade.diagnosis.summary }}</dd></template></dl>
      </details>
    </details>
  </section>
</template>
