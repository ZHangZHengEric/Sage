<script setup>
import { computed, nextTick, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import MessageBody from './MessageBody.vue'
import ToolCallCard from './ToolCallCard.vue'
import InteractionPrompt from './InteractionPrompt.vue'
import { interactionCallId, textOf, transcriptMessages } from '../agui/presentation.js'
import { toolState } from '../agui/tool-state.js'
import '../conversation-process.css'
const props = defineProps({ messages: { type: Array, default: () => [] }, pending: Boolean, interaction: { type: Object, default: null }, readOnly: Boolean, decisionBusy: Boolean, decisionError: String, answer: String })
const emit = defineEmits(['decide', 'update:answer', 'open-workspace'])
const root = ref(null), copied = ref(''), copyError = ref('')
const results = computed(() => new Map(props.messages.filter(message => message.role === 'tool' && message.toolCallId).map(message => [message.toolCallId, message])))
const visibleMessages = computed(() => transcriptMessages(props.messages))
const copyableReplies = computed(() => {
  const ids = new Set()
  let foundReply = false
  for (const message of [...visibleMessages.value].reverse()) {
    if (message.role === 'user') foundReply = false
    else if (message.role === 'assistant' && textOf(message).trim() && !foundReply) {
      ids.add(message.id)
      foundReply = true
    }
  }
  return ids
})
const linkedCall = computed(() => interactionCallId(props.messages, props.interaction))
const pendingLabel = computed(() => {
  const states = props.messages.flatMap(message => (message.toolCalls || []).map(call => toolState(call, results.value.has(call.id))))
  return states.includes('running') ? '正在执行工具…' : states.includes('reconciling') ? '正在核对结果…' : states.includes('queued') ? '等待执行工具…' : '正在生成…'
})
function continuation(message) { return message.role === 'assistant' && !textOf(message).trim() }
function roleLabel(role) { return { user: '你', assistant: '助手', tool: '工具', reasoning: '思考过程' }[role] || role }
async function copyMessage(message) {
  try { await navigator.clipboard.writeText(textOf(message)); copied.value = message.id; copyError.value = '' }
  catch { copyError.value = '复制失败，请选择消息后复制' }
}
async function focusInteraction() {
  await nextTick()
  const target = root.value?.querySelector('[data-active-interaction]')
  target?.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
  target?.focus({ preventScroll: true })
}
defineExpose({ focusInteraction })
</script>
<template>
  <div ref="root" class="transcript conversation-transcript" role="log" aria-live="polite" aria-relevant="additions">
    <article v-for="message in visibleMessages" :key="message.id" class="msg" :class="{ 'message-continuation': continuation(message) }" :data-role="message.role">
      <div class="msg-row">
        <div v-if="message.role === 'assistant' && !continuation(message)" class="msg-avatar" aria-hidden="true"><img src="/sage_logo.svg" alt="" /></div>
        <div class="msg-stack">
          <header v-if="message.role !== 'reasoning' && message.role !== 'user' && message.role !== 'assistant' && !continuation(message)" class="msg-meta">{{ roleLabel(message.role) }}</header>
          <MessageBody v-if="message.role === 'assistant' && textOf(message)" :text="textOf(message)" />
          <pre v-else-if="message.role === 'tool'" class="orphan-tool-result">{{ textOf(message) }}</pre>
          <details v-else-if="message.role === 'reasoning'" :key="`${message.id}-${Boolean(message.reasoningStreaming && pending)}`" class="process-reasoning" :open="Boolean(message.reasoningStreaming && pending)">
            <summary><AppIcon name="model" /><span>思考过程</span><span class="reasoning-state">{{ message.reasoningStreaming && pending ? '思考中' : '已结束' }}</span><AppIcon name="chevron" /></summary>
            <p>{{ textOf(message) }}</p>
          </details>
          <p v-else-if="message.role !== 'assistant'" class="plain">{{ textOf(message) }}</p>
          <span v-if="message.steeringPending" class="message-steering-status">待接收</span>
          <section v-if="message.toolCalls?.length" class="process-group" aria-label="工具调用">
            <ToolCallCard v-for="call in message.toolCalls" :key="call.id" :call="call" :result="results.get(call.id)" @open-workspace="$emit('open-workspace')">
              <div v-if="interaction && linkedCall === call.id" data-active-interaction tabindex="-1" class="interaction-location">
                <InteractionPrompt :interaction="interaction" :busy="decisionBusy" :read-only="readOnly" :answer="answer" :error="decisionError" @update:answer="$emit('update:answer', $event)" @decide="$emit('decide', $event)" />
              </div>
            </ToolCallCard>
          </section>
          <div v-if="copyableReplies.has(message.id) && !pending" class="message-actions"><button type="button" @click="copyMessage(message)"><AppIcon name="copy" />{{ copied === message.id ? '已复制' : '复制回复' }}</button></div>
        </div>
      </div>
    </article>
    <div v-if="interaction && !linkedCall" data-active-interaction tabindex="-1" class="interaction-location standalone-interaction"><InteractionPrompt :interaction="interaction" :busy="decisionBusy" :read-only="readOnly" :answer="answer" :error="decisionError" @update:answer="$emit('update:answer', $event)" @decide="$emit('decide', $event)" /></div>
    <p v-if="copyError" class="message-copy-feedback" role="status">{{ copyError }}</p>
    <p v-if="interaction" class="sr-only" role="status">{{ decisionBusy ? '正在提交决定…' : interaction.interaction_type === 'approval' ? '等待审批' : '等待回复' }}</p>
    <p v-else-if="pending" class="process-pending" role="status" aria-busy="true"><i class="process-spinner" aria-hidden="true" />{{ pendingLabel }}</p>
  </div>
</template>
