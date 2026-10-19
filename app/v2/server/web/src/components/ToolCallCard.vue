<script setup>
import { computed, nextTick, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { toolState, toolStateLabels } from '../agui/tool-state.js'
import { argumentsOf, parseArguments, pretty, resultFile, textOf, toolName } from '../agui/presentation.js'
import { toolPresentation } from '../resource-presentation.js'
const props = defineProps({ call: { type: Object, required: true }, result: Object })
defineEmits(['open-workspace'])
const id = useId(), argsButton = ref(null), resultButton = ref(null), expanded = ref(false), tab = ref('args'), feedback = ref('')
const state = computed(() => toolState(props.call, Boolean(props.result)))
const name = computed(() => toolName(props.call))
const title = computed(() => toolPresentation({ name: name.value, source: props.call.source }).title)
const args = computed(() => pretty(argumentsOf(props.call)))
const output = computed(() => textOf(props.result))
const file = computed(() => resultFile(props.call, props.result))
const target = computed(() => {
  const value = parseArguments(argumentsOf(props.call))
  return [value?.file_path, value?.relative_path, value?.path, value?.command].find(value => typeof value === 'string') || ''
})
const icons = { preparing: 'more', queued: 'clock', awaiting_approval: 'shield', not_executed: 'ban', completed: 'check', failed: 'alert', denied: 'ban', cancelled: 'close', unknown: 'help', reconciling: 'search', incomplete: 'alert' }
const noOutput = computed(() => ({ denied: '这次调用已拒绝，没有执行输出。', not_executed: '这次调用未执行，没有执行输出。', unknown: '结果待确认，请先核对实际状态。', reconciling: '正在核对实际结果。', cancelled: '本次调用已取消，尚无输出。', incomplete: '调用未执行完毕，尚无完整输出。' }[state.value] || '尚未收到输出。'))
watch(state, value => { if (value === 'failed') { expanded.value = true; tab.value = 'result' } }, { immediate: true })
async function copy() {
  try { await navigator.clipboard.writeText(tab.value === 'args' ? args.value : output.value); feedback.value = '已复制' }
  catch { feedback.value = '复制失败，请选择内容后复制' }
}
function moveTab(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  tab.value = event.key === 'Home' ? 'args' : event.key === 'End' ? 'result' : tab.value === 'args' ? 'result' : 'args'
  nextTick(() => (tab.value === 'args' ? argsButton.value : resultButton.value)?.focus())
}
</script>
<template>
  <div class="process-call" :data-state="state">
    <details class="process-tool" :open="expanded" @toggle="expanded = $event.target.open">
      <summary><span class="process-glyph"><AppIcon name="tools" /></span><span class="process-label"><strong>{{ title }}</strong><code :title="target">{{ title !== name ? name : '' }}{{ title !== name && target ? ' · ' : '' }}{{ target }}</code></span><span class="process-state" :data-state="state"><i v-if="state === 'running'" class="process-spinner" aria-hidden="true" /><AppIcon v-else :name="icons[state] || 'help'" />{{ toolStateLabels[state] || '结果待确认' }}</span><AppIcon class="process-chevron" name="chevron" /></summary>
      <div class="process-tool-body">
        <div class="process-tool-tabs" role="tablist" :aria-label="`${name} 详情`" @keydown="moveTab">
          <button :id="`${id}-args-tab`" ref="argsButton" type="button" role="tab" :aria-selected="tab === 'args'" :aria-controls="`${id}-args`" :tabindex="tab === 'args' ? 0 : -1" @click="tab = 'args'; feedback = ''">参数</button>
          <button :id="`${id}-result-tab`" ref="resultButton" type="button" role="tab" :aria-selected="tab === 'result'" :aria-controls="`${id}-result`" :tabindex="tab === 'result' ? 0 : -1" @click="tab = 'result'; feedback = ''">{{ state === 'failed' ? '输出 · 错误' : '输出' }}</button>
        </div>
        <div v-show="tab === 'args'" :id="`${id}-args`" role="tabpanel" :aria-labelledby="`${id}-args-tab`" tabindex="0"><pre v-if="args"><code>{{ args }}</code></pre><p v-else class="process-no-output">暂无参数</p></div>
        <div v-show="tab === 'result'" :id="`${id}-result`" role="tabpanel" :aria-labelledby="`${id}-result-tab`" tabindex="0"><pre v-if="output" :class="{ 'process-error-output': state === 'failed' }"><code>{{ output }}</code></pre><p v-else class="process-no-output">{{ noOutput }}</p></div>
        <div class="process-copy-row"><span role="status">{{ feedback }}</span><button type="button" :disabled="!(tab === 'args' ? args : output)" @click="copy"><AppIcon name="copy" />复制{{ tab === 'args' ? '参数' : '输出' }}</button></div>
      </div>
    </details>
    <div v-if="file && expanded && tab === 'result'" class="process-file"><AppIcon name="file" /><code>{{ file }}</code><button type="button" @click="$emit('open-workspace')">在工作空间查看<AppIcon name="chevron" /></button></div>
    <slot />
  </div>
</template>
