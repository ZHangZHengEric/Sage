<template>
  <div class="shell-container bg-black text-green-400 font-mono text-sm p-4 h-full overflow-auto" ref="scrollEl">
    <div class="shell-header text-gray-500 mb-2 flex items-center gap-2">
      <span class="select-all">$ {{ shellCommand }}</span>
      <span
        v-if="showLiveBadge"
        class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide bg-emerald-900/40 text-emerald-300 border border-emerald-700/50"
      >
        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        live
      </span>
    </div>

    <!-- 实时输出区域：命令尚未结束时优先展示 progress 通道增量 -->
    <template v-if="hasLiveSegments && !hasFinalResult">
      <div
        v-for="(seg, idx) in liveSegments"
        :key="idx"
        :class="[
          'whitespace-pre-wrap break-all',
          seg.stream === 'stderr' ? 'text-red-400' : 'text-green-400',
        ]"
      >{{ seg.text }}</div>
    </template>

    <!-- 命令完成后展示最终 stdout / stderr（来自 tool message 的完整结果） -->
    <template v-else>
      <div v-if="shellOutput" class="shell-output whitespace-pre-wrap break-all">{{ shellOutput }}</div>
      <div v-if="shellError" class="shell-error text-red-400 mt-2 whitespace-pre-wrap break-all">{{ shellError }}</div>
    </template>

    <!-- 完成后的状态行：exit_code 等 -->
    <div
      v-if="hasFinalResult && exitCode !== null"
      class="mt-2 pt-2 border-t border-gray-700 text-xs"
    >
      <span class="text-gray-500">exit_code: </span>
      <span :class="exitCode === 0 ? 'text-emerald-400' : 'text-red-400'">{{ exitCode }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, nextTick, watch } from 'vue'

const props = defineProps({
  toolArgs: { type: Object, default: () => ({}) },
  toolResult: { type: Object, default: null },
  liveOutput: { type: String, default: '' },
  liveSegments: { type: Array, default: () => [] },
  live: { type: Boolean, default: false }
})

const scrollEl = ref(null)

const shellCommand = computed(() => props.toolArgs.command || props.toolArgs.cmd || '')

const hasFinalResult = computed(() => !!props.toolResult)
const hasLiveSegments = computed(() => Array.isArray(props.liveSegments) && props.liveSegments.length > 0)

// 命令仍在运行（未拿到最终 toolResult），且 live=true（progress 流未关闭）
const showLiveBadge = computed(() => !hasFinalResult.value && props.live)

const parsedResult = computed(() => {
  if (!props.toolResult) return null
  let content = props.toolResult.content
  if (typeof content === 'string') {
    try {
      return JSON.parse(content)
    } catch {
      return { stdout: content }
    }
  }
  return content || null
})

const shellOutput = computed(() => {
  const r = parsedResult.value
  if (!r) return ''
  return r.stdout || r.output || (typeof r === 'string' ? r : '')
})

const shellError = computed(() => {
  const r = parsedResult.value
  if (!r) return ''
  return r.stderr || r.error || ''
})

const exitCode = computed(() => {
  const r = parsedResult.value
  if (!r || typeof r !== 'object') return null
  if (typeof r.exit_code === 'number') return r.exit_code
  if (typeof r.return_code === 'number') return r.return_code
  return null
})

// 自动滚到底部：仅在用户当前已贴底时执行，避免抢占用户向上滚动查看历史的操作
const _isStickyBottom = () => {
  const el = scrollEl.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 32
}

const scrollToBottomSoon = () => {
  nextTick(() => {
    const el = scrollEl.value
    if (!el) return
    el.scrollTop = el.scrollHeight
  })
}

// 实时段累积时自动滚动
watch(
  () => (props.liveSegments || []).length,
  () => {
    if (_isStickyBottom()) scrollToBottomSoon()
  }
)

// 最终结果到达时再滚一次
watch(
  () => props.toolResult,
  () => {
    if (_isStickyBottom()) scrollToBottomSoon()
  }
)
</script>
