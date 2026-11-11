<script setup>
import { computed, ref, shallowRef, watch } from "vue";
import { api } from "../api.js";
import { duration as formatDuration, purposeLabels } from "../performance.js";
import FieldHelp from "./FieldHelp.vue";
import FormDrawer from "./FormDrawer.vue";
import { toolName } from "../agui/presentation.js";

const props = defineProps({ threadId: String, runId: String, messages: { type: Array, default: () => [] }, owner: Object });
const emit = defineEmits(["close"]);
const request = shallowRef({ loading: false });
const PAGE_SIZE = 24;
const visibleCount = ref(PAGE_SIZE);
function duration(ms) {
  return ms != null && ms >= 60000 && ms < 3600000 ? `${(ms / 1000).toFixed(2)} s` : formatDuration(ms);
}
const metrics = [
  ["total_ms", "总执行耗时"],
  ["first_token_ms", "首 token"],
  ["first_text_ms", "首段正文 · 从本轮开始"],
  ["first_text_request_ms", "首段正文 · 从该次模型调用开始"],
  ["model_ttft_ms", "首个模型请求的首 token"],
  ["model_ms", "模型调用"],
  ["tool_ms", "工具执行"],
  ["framework_ms", "框架开销"],
  ["overlap_ms", "模型与工具重叠"],
  ["waiting_ms", "暂停等待"],
];
const timing = computed(() => request.value.data?.timing);
const timeline = computed(() => timing.value?.timeline);
const labels = {
  preparation: "运行准备",
  model: "模型调用",
  tool: "工具调用",
  framework: "框架开销",
  cleanup: "运行收尾",
  waiting: "暂停等待",
  first_token: "首 token",
};
const totals = computed(() => {
  const value = timing.value;
  if (!value?.total_ms || value.coverage !== "complete") return null;
  const groups = [
    { label: labels.model, milliseconds: value.model_ms },
    { label: labels.tool, milliseconds: value.tool_ms },
    { label: labels.framework, milliseconds: value.framework_ms },
  ];
  const longest = groups.reduce((max, group) => (group.milliseconds ?? 0) > (max.milliseconds ?? 0) ? group : max);
  return {
    ...longest,
    share: Math.round((longest.milliseconds ?? 0) / value.total_ms * 100),
  };
});
const rows = computed(() => {
  const value = timeline.value;
  if (!value?.wall_ms) return [];
  const names = new Map();
  for (const message of props.messages) {
    for (const call of message.toolCalls || []) {
      const name = toolName(call);
      // Some providers can reuse a call ID across rounds. Ambiguous IDs stay unnamed.
      names.set(call.id, names.has(call.id) && names.get(call.id) !== name ? null : name);
    }
  }
  let model = 0;
  return value.entries.map((entry) => {
    const point = entry.kind === "first_token";
    const milliseconds = entry.end_ms - entry.start_ms;
    let label = labels[entry.kind];
    if (entry.kind === "model") {
      const purpose = purposeLabels[entry.purpose];
      label = `${purpose || label} #${++model}`;
    }
    return {
      ...entry,
      label,
      toolTitle: entry.tool_call_id ? names.get(entry.tool_call_id) : undefined,
      point,
      milliseconds,
      offset: entry.start_ms / value.wall_ms * 100,
      width: milliseconds / value.wall_ms * 100,
    };
  });
});
const longestRow = computed(() => {
  if (timeline.value?.truncated) return null;
  let longest = null;
  for (const row of rows.value) {
    if (!row.point && row.kind !== "waiting" && (!longest || row.milliseconds > longest.milliseconds)) {
      longest = row;
    }
  }
  return longest;
});

watch(() => [props.threadId, props.runId, props.owner], async ([threadId, runId, owner], _, cleanup) => {
  if (!runId) return;
  visibleCount.value = PAGE_SIZE;
  const controller = new AbortController();
  cleanup(() => controller.abort());
  request.value = { loading: true };
  try {
    const data = await api.threadRunTiming(threadId, runId, owner, controller.signal);
    if (!controller.signal.aborted) request.value = { loading: false, data };
  } catch {
    if (!controller.signal.aborted) request.value = { loading: false, error: true };
  }
}, { immediate: true });
</script>

<template>
  <FormDrawer
    :model-value="Boolean(runId)"
    title="本轮耗时"
    centered
    panel-class="run-timing-dialog"
    @update:model-value="emit('close')"
  >
    <p v-if="request.loading" class="timing-note" role="status">正在读取耗时…</p>
    <p v-else-if="request.error" class="timing-note" role="alert">耗时读取失败，请稍后重试。</p>
    <p v-else-if="!timing" class="timing-note" role="status">{{
      request.data?.state === "suspended" ? "本轮正在等待输入，结束后可查看完整耗时。" : "暂无本轮耗时记录。"
    }}</p>
    <template v-else>
      <dl class="timing-summary">
        <div><dt>总执行耗时</dt><dd>{{ duration(timing.total_ms) }}</dd></div>
        <div v-if="totals">
          <dt>耗时最多 · {{ totals.label }}</dt>
          <dd>{{ duration(totals.milliseconds) }} <small>· {{ totals.share }}%</small></dd>
        </div>
      </dl>
      <section v-if="rows.length" class="timing-chart" aria-label="本轮执行时序">
        <div class="timing-axis">
          <strong>阶段时序</strong>
          <div><span>0</span><span>{{ duration(timeline?.wall_ms) }}</span></div>
          <span>耗时</span>
        </div>
        <ol class="timing-rows" role="list">
          <li
            v-for="(row, index) in rows.slice(0, visibleCount)"
            :key="index"
            :data-kind="row.kind"
            :data-longest="row === longestRow || undefined"
            :title="row.point ? `+${duration(row.start_ms)}` : `+${duration(row.start_ms)} – +${duration(row.end_ms)}`"
          >
            <span class="timing-label">
              {{ row.label }}
              <FieldHelp v-if="row.toolTitle" label="工具调用" trigger-label="查看工具名称" :text="row.toolTitle" title="" />
            </span>
            <div class="timing-track" aria-hidden="true">
              <i
                :class="row.point ? 'timing-point' : 'timing-bar'"
                :style="{ left: row.offset + '%', width: row.point ? undefined : row.width + '%' }"
              />
            </div>
            <span class="timing-value">
              {{ row.point ? `+${duration(row.start_ms)}` : duration(row.milliseconds) }}
              <span v-if="!row.point" class="sr-only">，起点 +{{ duration(row.start_ms) }}</span>
            </span>
          </li>
        </ol>
        <button v-if="visibleCount < rows.length" type="button" class="btn ghost timing-more" @click="visibleCount += PAGE_SIZE">
          显示更多阶段（{{ rows.length - visibleCount }}）
        </button>
        <p v-if="longestRow" class="timing-note">
          最长执行段 · {{ longestRow.label }} · {{ duration(longestRow.milliseconds) }}
        </p>
        <p v-if="timeline?.truncated" class="timing-note">仅显示前 {{ rows.length }} 个阶段和时间点。</p>
        <p v-if="timing.waiting_ms" class="timing-note">时间轴含暂停等待，汇总的执行耗时扣除了这段时间。</p>
      </section>
      <details class="timing-details" :open="!rows.length">
        <summary>汇总指标</summary>
        <dl class="timing-metrics">
          <div v-for="[key, label] in metrics" :key="key">
            <dt>{{ label }}</dt>
            <dd>{{ duration(timing[key]) }}</dd>
          </div>
        </dl>
      </details>
      <p v-if="timing.coverage === 'incomplete'" class="timing-note">{{
        timing.scope === "execution_only" ? "仅记录了执行阶段，部分数据缺失。" : "本轮采集不完整。"
      }}</p>
    </template>
  </FormDrawer>
</template>

<style scoped>
:global(.form-drawer.form-dialog.run-timing-dialog) {
  width: min(43rem, calc(100vw - 1.5rem));
}
.timing-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin: 0 0 16px;
}
.timing-summary > div {
  flex: 1 0 auto;
}
.timing-summary dt {
  color: var(--muted-foreground);
  font-size: 12px;
}
.timing-summary dd {
  margin: 3px 0 0;
  font-size: 17px;
  font-weight: 650;
}
.timing-summary small {
  color: var(--muted-foreground);
  font-size: 12px;
}
.timing-axis,
.timing-rows li {
  display: grid;
  grid-template-columns: minmax(5.5rem, 9rem) minmax(0, 1fr) 5.5rem;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.timing-axis {
  margin-bottom: 4px;
  color: var(--muted-foreground);
}
.timing-axis strong {
  color: var(--foreground);
}
.timing-axis > div {
  display: flex;
  justify-content: space-between;
  font-variant-numeric: tabular-nums;
}
.timing-axis > :last-child,
.timing-value {
  text-align: right;
}
.timing-label {
  overflow-wrap: anywhere;
}
.timing-rows {
  list-style: none;
  padding: 0;
  margin: 0;
}
.timing-rows li {
  padding: 5px 0;
  border-bottom: 1px solid var(--border);
  --phase: var(--border-hover);
}
.timing-rows li[data-longest] {
  font-weight: 700;
}
.timing-rows li[data-kind="model"] {
  --phase: var(--accent);
}
.timing-rows li[data-kind="tool"] {
  --phase: var(--status-success);
}
.timing-rows li[data-kind="waiting"] {
  --phase: var(--status-warning);
}
.timing-track {
  position: relative;
  height: 13px;
  border-inline: 1px solid var(--border);
  background: repeating-linear-gradient(to right, var(--border) 0 1px, transparent 1px 25%);
}
.timing-bar,
.timing-point {
  position: absolute;
  top: 2px;
  height: 9px;
}
.timing-bar {
  min-width: 1px;
  border-radius: 2px;
  background: var(--phase);
}
.timing-point {
  width: 2px;
  transform: translateX(-50%);
  background: var(--foreground);
}
.timing-value {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.timing-more,
.timing-details {
  margin-top: 12px;
}
.timing-details summary {
  color: var(--muted-foreground);
  font-size: 13px;
}
.timing-metrics {
  margin: 0;
}
.timing-metrics > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.timing-metrics > div:first-child {
  font-weight: 650;
}
.timing-metrics dd {
  margin: 0;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.timing-note {
  margin: 12px 0 0;
  color: var(--muted-foreground);
  font-size: 12px;
  overflow-wrap: anywhere;
}
@media (max-width: 640px) {
  .timing-axis,
  .timing-rows li {
    grid-template-columns: 5.25rem minmax(0, 1fr) 4.25rem;
    gap: 6px;
  }
}
</style>
