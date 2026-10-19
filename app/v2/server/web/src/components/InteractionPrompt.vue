<script setup>
import { computed, onMounted, onUnmounted, ref, useId } from 'vue'
import AppIcon from './AppIcon.vue'
import FieldHelp from './FieldHelp.vue'
import { parseArguments, pretty, rememberDescription } from '../agui/presentation.js'
const props = defineProps({ interaction: { type: Object, default: null }, busy: Boolean, readOnly: Boolean, answer: { type: String, default: '' }, error: { type: String, default: '' } })
const emit = defineEmits(['decide', 'update:answer'])
const id = useId(), more = ref(null)
const TEXT_DECISIONS = new Set(['submit', 'change_direction'])
const LABELS = { approve_once: '允许这一次', approve_and_remember: '允许并记住', deny: '拒绝这次调用', cancel: '取消本次运行', submit: '提交回答', retry: '重试', change_direction: '换个方向' }
const levels = { none: '无副作用', read: '读取', write: '写入', reversible: '可撤销操作', irreversible: '不可逆操作' }
const payload = computed(() => props.interaction?.payload || {})
const decisions = computed(() => props.interaction?.allowed_decisions || [])
const approval = computed(() => props.interaction?.interaction_type === 'approval')
const mainDecisions = computed(() => decisions.value.filter(name => !approval.value || !['approve_and_remember', 'cancel'].includes(name)))
const moreDecisions = computed(() => approval.value ? decisions.value.filter(name => ['approve_and_remember', 'cancel'].includes(name)) : [])
const wantsText = computed(() => decisions.value.some(name => TEXT_DECISIONS.has(name)))
const title = computed(() => approval.value && payload.value.tool_name ? `允许运行 ${payload.value.tool_name} 吗？` : payload.value.title || '智能体在等你的回答')
const args = computed(() => pretty(payload.value.arguments))
const target = computed(() => { const value = parseArguments(payload.value.arguments); return typeof value?.file_path === 'string' ? value.file_path : '' })
const mode = computed(() => parseArguments(payload.value.arguments)?.mode)
function outside(event) { if (more.value && !more.value.contains(event.target)) more.value.open = false }
onMounted(() => { if (typeof document !== 'undefined') document.addEventListener('pointerdown', outside) })
onUnmounted(() => { if (typeof document !== 'undefined') document.removeEventListener('pointerdown', outside) })
function disabled(name) { return props.readOnly || props.busy || (TEXT_DECISIONS.has(name) && !props.answer.trim()) }
function choose(name) {
  if (!decisions.value.includes(name) || disabled(name)) return
  if (more.value) more.value.open = false
  emit('decide', { decision: name, payload: TEXT_DECISIONS.has(name) ? { text: props.answer.trim() } : {} })
}
</script>
<template>
  <section v-if="interaction" class="conversation-interaction" :class="{ 'is-approval': approval }" role="group" :aria-label="title" :aria-busy="busy">
    <header class="interaction-heading"><AppIcon :name="approval ? 'shield' : 'chat'" /><h2>{{ title }}</h2><span v-if="payload.side_effect_level" class="interaction-risk">{{ levels[payload.side_effect_level] || payload.side_effect_level }}</span></header>
    <div v-if="target" class="interaction-target"><AppIcon name="file" /><code>{{ target }}</code><span v-if="mode">{{ mode === 'overwrite' ? '覆盖写入' : mode === 'append' ? '追加写入' : mode }}</span></div>
    <p v-if="payload.risk_reason || payload.prompt || payload.guidance" class="interaction-prompt">{{ payload.risk_reason || payload.prompt || payload.guidance }}</p>
    <details v-if="args" class="interaction-arguments"><summary>查看完整调用参数<AppIcon name="chevron" /></summary><pre><code>{{ args }}</code></pre></details>
    <p v-if="error" class="interaction-error" role="alert">{{ error }}</p>
    <p v-if="readOnly" class="interaction-readonly"><AppIcon name="lock" />等待会话所属用户处理</p>
    <template v-else>
      <label v-if="wantsText" class="interaction-answer-label" :for="`${id}-answer`">你的回答</label>
      <textarea v-if="wantsText" :id="`${id}-answer`" :value="answer" rows="2" :disabled="busy" :placeholder="payload.questions?.[0]?.placeholder || '写下你的回答…'" @input="$emit('update:answer', $event.target.value)" />
      <div class="interaction-actions">
        <button v-for="(name, index) in mainDecisions" :key="name" class="btn" :class="name === 'approve_once' || name === 'submit' ? 'cta' : 'ghost'" type="button" :disabled="disabled(name)" @click="choose(name)"><i v-if="busy && index === 0" class="process-spinner" aria-hidden="true" />{{ busy && index === 0 ? '正在提交…' : LABELS[name] || name }}</button>
        <details v-if="moreDecisions.length" ref="more" class="interaction-more" @keydown.esc.stop.prevent="more.open = false" @focusout="event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false }">
          <summary :aria-disabled="busy" @click="event => { if (busy) event.preventDefault() }">更多操作<AppIcon name="chevron" /></summary>
          <div class="interaction-more-body"><div v-for="name in moreDecisions" :key="name" class="interaction-extra"><button type="button" :disabled="disabled(name)" @click="choose(name)">{{ LABELS[name] || name }}</button><FieldHelp v-if="name === 'approve_and_remember'" label="记住审批" :text="rememberDescription(payload)" /></div></div>
        </details>
      </div>
    </template>
  </section>
</template>
