<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { api } from '../api.js'
import { createAguiAgent, runAgui } from '../agui/session.js'
import { messagesFromEvents } from '../agui/replay.js'
import AguiTranscript from '../components/AguiTranscript.vue'
import ThreadList from '../components/ThreadList.vue'

const threads = ref([])
const threadId = ref('')
const text = ref('')
const messages = ref([])
const pending = ref(false)
const error = ref('')
const scroller = ref(null)
const input = ref(null)
const agent = shallowRef(null)

const threadTitle = computed(() => {
  const current = threads.value.find((item) => item.thread_id === threadId.value)
  return current?.title || '新对话'
})

function newId(prefix) {
  return `${prefix}-${crypto.randomUUID()}`
}

function bindAgent() {
  agent.value = createAguiAgent({
    onMessages(next) {
      messages.value = next
      nextTick(() => scroller.value?.scrollTo(0, scroller.value.scrollHeight))
    },
    onError(message) {
      error.value = message
    },
  })
}

function resizeInput() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

async function loadThreads() {
  threads.value = await api.listThreads()
}

async function openThread(id) {
  threadId.value = id
  error.value = ''
  const events = await api.threadEvents(id)
  const history = messagesFromEvents(events)
  messages.value = history
  agent.value.threadId = id
  agent.value.setMessages(history)
  await nextTick()
  scroller.value?.scrollTo(0, scroller.value.scrollHeight)
}

function startNew() {
  threadId.value = newId('thread')
  messages.value = []
  error.value = ''
  agent.value.threadId = threadId.value
  agent.value.setMessages([])
  nextTick(() => input.value?.focus())
}

async function send() {
  const content = text.value.trim()
  if (!content || pending.value) return
  if (!threadId.value) threadId.value = newId('thread')
  text.value = ''
  nextTick(resizeInput)
  pending.value = true
  error.value = ''
  try {
    await runAgui(agent.value, {
      threadId: threadId.value,
      runId: newId('run'),
      content,
    })
    await loadThreads()
  } catch (exc) {
    error.value = exc.message
  } finally {
    pending.value = false
    await nextTick()
    scroller.value?.scrollTo(0, scroller.value.scrollHeight)
    input.value?.focus()
  }
}

onMounted(async () => {
  bindAgent()
  try {
    await loadThreads()
    if (threads.value[0]) await openThread(threads.value[0].thread_id)
    else startNew()
  } catch (exc) {
    error.value = exc.message
  }
})

onUnmounted(() => {
  agent.value?.abortRun?.()
})
</script>

<template>
  <section class="chat-layout">
    <ThreadList
      :threads="threads"
      :active-id="threadId"
      @select="openThread"
      @create="startNew"
    />
    <div class="thread-root">
      <header class="thread-bar">
        <h1>{{ threadTitle }}</h1>
      </header>
      <div ref="scroller" class="thread-viewport">
        <AguiTranscript
          :messages="messages"
          :pending="pending"
        />
      </div>
      <p v-if="error" class="error thread-error" role="alert">{{ error }}</p>
      <footer class="thread-footer">
        <form class="composer" @submit.prevent="send">
          <label class="sr-only" for="chat-input">消息</label>
          <textarea
            id="chat-input"
            ref="input"
            v-model="text"
            rows="1"
            placeholder="输入消息…"
            :disabled="pending"
            @input="resizeInput"
            @keydown.enter.exact.prevent="send"
            @keydown.meta.enter.prevent="send"
          />
          <button
            class="send"
            type="submit"
            :disabled="pending || !text.trim()"
            aria-label="发送"
          >
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
              <path fill="currentColor" d="M8 2.4a.75.75 0 0 1 .75.75v8.19l2.72-2.72a.75.75 0 1 1 1.06 1.06l-4 4a.75.75 0 0 1-1.06 0l-4-4a.75.75 0 0 1 1.06-1.06l2.72 2.72V3.15A.75.75 0 0 1 8 2.4Z" />
            </svg>
          </button>
        </form>
      </footer>
    </div>
  </section>
</template>
