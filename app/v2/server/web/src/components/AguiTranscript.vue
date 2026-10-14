<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import AppIcon from './AppIcon.vue'
import { toolState, toolStateLabels } from '../agui/tool-state.js'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  pending: { type: Boolean, default: false },
  interaction: { type: Object, default: null },
})

// Join only for display: the SDK still receives the original protocol messages.
const results = computed(() => new Map(props.messages
  .filter(message => message.role === 'tool' && message.toolCallId)
  .map(message => [message.toolCallId, message])))
const visibleMessages = computed(() => {
  const calls = new Set(props.messages.flatMap(message => (message.toolCalls || []).map(call => call.id)))
  return props.messages.filter(message => {
    if (message.role === 'tool' && calls.has(message.toolCallId)) return false
    return textOf(message).trim() || message.toolCalls?.length
  })
})

marked.setOptions({ breaks: true, gfm: true })

function textOf(message) {
  const content = message.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((part) => (typeof part === 'string' ? part : part?.text || ''))
      .join('')
  }
  return ''
}

function markdown(text) {
  const html = marked.parse(text || '', { async: false })
  return String(html).replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
}

const statusIcons = {
  preparing: 'more', queued: 'clock', awaiting_approval: 'shield',
  completed: 'check', failed: 'alert', denied: 'ban', cancelled: 'close',
  unknown: 'alert', reconciling: 'search', incomplete: 'alert',
}

function toolName(call) {
  return call?.function?.name || call?.name || 'tool'
}

function toolArgs(call) {
  const args = call?.function?.arguments ?? call?.arguments ?? ''
  try {
    return JSON.stringify(typeof args === 'string' ? JSON.parse(args) : args, null, 2)
  } catch {
    // Streaming arguments may not form a complete JSON value yet.
    return args
  }
}

function roleLabel(role) {
  if (role === 'user') return '你'
  if (role === 'assistant') return '助手'
  if (role === 'tool') return '工具'
  if (role === 'reasoning') return '推理'
  return role
}
</script>

<template>
  <div class="transcript" role="log" aria-live="polite" aria-relevant="additions">
    <article
      v-for="message in visibleMessages"
      :key="message.id"
      class="msg"
      :data-role="message.role"
    >
      <div class="msg-row">
        <div v-if="message.role === 'assistant'" class="msg-avatar" aria-hidden="true">S</div>
        <div class="msg-stack">
          <header v-if="message.role !== 'reasoning'" class="msg-meta">{{ roleLabel(message.role) }}</header>
          <div
            v-if="message.role === 'assistant'"
            class="md"
            v-html="markdown(textOf(message))"
          />
          <pre v-else-if="message.role === 'tool'" class="tool-body">{{ textOf(message) }}</pre>
          <details
            v-else-if="message.role === 'reasoning'"
            :key="`${message.id}-${Boolean(message.reasoningStreaming && pending)}`"
            :open="Boolean(message.reasoningStreaming && pending)"
          >
            <summary class="reasoning-summary"><AppIcon name="model" /><span>思考过程</span><AppIcon v-if="!message.reasoningStreaming" name="check" /><AppIcon name="chevron" /></summary>
            <p class="reason">{{ textOf(message) }}</p>
          </details>
          <p v-else class="plain">{{ textOf(message) }}</p>
          <ul v-if="message.toolCalls?.length" class="tools">
            <li v-for="call in message.toolCalls" :key="call.id">
              <details class="tool-detail">
                <summary><AppIcon :name="toolName(call) === 'load_skill' ? 'skill' : toolName(call) === 'list_dir' ? 'folder' : 'tools'" /><strong>{{ toolName(call) }}</strong><span
                  class="tool-status"
                  :data-state="toolState(call, results.has(call.id))"
                  :title="toolStateLabels[toolState(call, results.has(call.id))]"
                  :aria-label="toolStateLabels[toolState(call, results.has(call.id))]"
                  role="img"
                ><span v-if="toolState(call) === 'running'" class="tool-spinner" aria-hidden="true" /><AppIcon v-else :name="statusIcons[toolState(call, results.has(call.id))]" /></span><AppIcon name="chevron" /></summary>
                <div class="tool-detail-body"><pre class="tool-args"><code>{{ toolArgs(call) }}</code></pre>
                <pre v-if="textOf(results.get(call.id) || {})">{{ textOf(results.get(call.id)) }}</pre></div>
              </details>
            </li>
          </ul>
        </div>
      </div>
    </article>
    <p v-if="interaction" class="pending" role="status">{{ interaction.interaction_type === 'approval' ? '等待审批' : '等待回复' }}</p>
    <p v-else-if="pending" class="pending" aria-busy="true">
      <span class="pending-dot" />
      正在生成…
    </p>
  </div>
</template>
