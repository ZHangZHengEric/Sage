<script setup>
import { marked } from 'marked'

defineProps({
  messages: { type: Array, default: () => [] },
  pending: { type: Boolean, default: false },
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

function toolName(call) {
  return call?.function?.name || call?.name || 'tool'
}

function toolArgs(call) {
  return call?.function?.arguments || call?.arguments || ''
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
      v-for="message in messages"
      :key="message.id"
      class="msg"
      :data-role="message.role"
    >
      <div class="msg-row">
        <div v-if="message.role === 'assistant'" class="msg-avatar" aria-hidden="true">S</div>
        <div class="msg-stack">
          <header class="msg-meta">{{ roleLabel(message.role) }}</header>
          <div
            v-if="message.role === 'assistant'"
            class="md"
            v-html="markdown(textOf(message))"
          />
          <pre v-else-if="message.role === 'tool'" class="tool-body">{{ textOf(message) }}</pre>
          <p v-else-if="message.role === 'reasoning'" class="reason">{{ textOf(message) }}</p>
          <p v-else class="plain">{{ textOf(message) }}</p>
          <ul v-if="message.toolCalls?.length" class="tools">
            <li v-for="call in message.toolCalls" :key="call.id">
              <strong>{{ toolName(call) }}</strong>
              <pre>{{ toolArgs(call) }}</pre>
            </li>
          </ul>
        </div>
      </div>
    </article>
    <p v-if="pending" class="pending" aria-busy="true">
      <span class="pending-dot" />
      正在生成…
    </p>
  </div>
</template>
