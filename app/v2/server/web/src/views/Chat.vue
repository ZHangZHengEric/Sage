<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { api } from '../api.js'
import { createAguiAgent, resumeAgui, runAgui } from '../agui/session.js'
import { messagesBeforeLastRun, messagesFromEvents, pendingInteraction } from '../agui/replay.js'
import AguiTranscript from '../components/AguiTranscript.vue'
import InteractionPrompt from '../components/InteractionPrompt.vue'
import ThreadList from '../components/ThreadList.vue'

const threads = ref([])
const threadId = ref('')
const text = ref('')
const messages = ref([])
const pending = ref(false)
const error = ref('')
const hasModel = ref(true)
const agents = ref([])
const interaction = ref(null)
// Where the Run in flight began. A resumed Run replays from its first event,
// so answering a question means rewinding the transcript back to here first.
const baseline = ref([])
const selectedAgentId = ref(localStorage.getItem('sage.server_v2.agent') || 'main')
const scroller = ref(null)
const input = ref(null)
const agent = shallowRef(null)

const currentThread = computed(() =>
  threads.value.find((item) => item.thread_id === threadId.value)
)
const threadTitle = computed(() => currentThread.value?.title || '新对话')
const agentLocked = computed(() => Boolean(currentThread.value?.agent_id))

function newId(prefix) {
  return `${prefix}-${crypto.randomUUID()}`
}

function bindAgent() {
  agent.value = createAguiAgent({
    agentId: selectedAgentId.value,
    onMessages(next) {
      messages.value = next
      nextTick(() => scroller.value?.scrollTo(0, scroller.value.scrollHeight))
    },
    onInteraction(next) {
      interaction.value = next
    },
    onError(message) {
      error.value = message
    },
  })
}

async function loadAgents() {
  agents.value = await api.listAgents()
  if (!agents.value.some((item) => item.id === selectedAgentId.value)) {
    selectedAgentId.value = agents.value[0]?.id || 'main'
  }
}

function selectAgent() {
  localStorage.setItem('sage.server_v2.agent', selectedAgentId.value)
  bindAgent()
  if (threadId.value) {
    agent.value.threadId = threadId.value
    agent.value.setMessages(messages.value)
  }
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

async function loadModels() {
  const items = await api.listModels()
  hasModel.value = items.length > 0
}

function applyThreadAgent(id) {
  const current = threads.value.find((item) => item.thread_id === id)
  if (current?.agent_id && current.agent_id !== selectedAgentId.value) {
    selectedAgentId.value = current.agent_id
    bindAgent()
  }
}

async function openThread(id) {
  threadId.value = id
  error.value = ''
  applyThreadAgent(id)
  const page = await api.threadEvents(id)
  const events = page?.events || []
  const history = messagesFromEvents(events)
  messages.value = history
  interaction.value = pendingInteraction(events)
  baseline.value = messagesBeforeLastRun(events) || history
  agent.value.threadId = id
  agent.value.setMessages(history)
  await nextTick()
  scroller.value?.scrollTo(0, scroller.value.scrollHeight)
}

function startNew() {
  threadId.value = newId('thread')
  messages.value = []
  interaction.value = null
  baseline.value = []
  error.value = ''
  agent.value.threadId = threadId.value
  agent.value.setMessages([])
  nextTick(() => input.value?.focus())
}

async function send() {
  const content = text.value.trim()
  if (!content || pending.value || interaction.value) return
  if (!threadId.value) threadId.value = newId('thread')
  text.value = ''
  nextTick(resizeInput)
  pending.value = true
  error.value = ''
  const message = { id: crypto.randomUUID(), role: 'user', content }
  baseline.value = [...messages.value, message]
  try {
    await runAgui(agent.value, {
      threadId: threadId.value,
      runId: newId('run'),
      message,
      agentId: selectedAgentId.value,
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

async function decide({ decision, payload }) {
  if (pending.value || !interaction.value) return
  const asked = interaction.value
  interaction.value = null
  pending.value = true
  error.value = ''
  try {
    // The resumed stream replays the Run from its first event so the client
    // rebuilds item state exactly; rewinding first is what keeps that replay
    // from doubling everything already on screen.
    agent.value.setMessages(baseline.value)
    await resumeAgui(agent.value, {
      threadId: threadId.value,
      runId: newId('run'),
      decision,
      payload,
    })
    await loadThreads()
  } catch (exc) {
    error.value = exc.message
    // The question outlived the answer, so it has to come back — otherwise the
    // thread is left waiting with nothing on screen to answer it.
    interaction.value = asked
  } finally {
    pending.value = false
    await nextTick()
    scroller.value?.scrollTo(0, scroller.value.scrollHeight)
  }
}

onMounted(async () => {
  bindAgent()
  try {
    await Promise.all([loadThreads(), loadModels(), loadAgents()])
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
        <label class="agent-pick">
          <span class="sr-only">智能体</span>
          <select
            v-model="selectedAgentId"
            :disabled="agentLocked"
            :title="agentLocked ? '本会话已绑定智能体' : '选择智能体'"
            @change="selectAgent"
          >
            <option v-for="item in agents" :key="item.id" :value="item.id">
              {{ item.name }}
            </option>
          </select>
        </label>
      </header>
      <div ref="scroller" class="thread-viewport">
        <AguiTranscript
          :messages="messages"
          :pending="pending"
        />
      </div>
      <p v-if="!hasModel" class="notice thread-error">
        还没有可用模型，请先到
        <router-link to="/models">模型</router-link>
        页配置后再发送。
      </p>
      <p v-if="error" class="error thread-error" role="alert">{{ error }}</p>
      <footer class="thread-footer">
        <InteractionPrompt :interaction="interaction" :busy="pending" @decide="decide" />
        <form class="composer" @submit.prevent="send">
          <label class="sr-only" for="chat-input">消息</label>
          <textarea
            id="chat-input"
            ref="input"
            v-model="text"
            rows="1"
            :placeholder="interaction ? '先回答上面的问题，再继续对话' : '输入消息…'"
            :disabled="pending || Boolean(interaction)"
            @input="resizeInput"
            @keydown.enter.exact.prevent="send"
            @keydown.meta.enter.prevent="send"
          />
          <button
            class="send"
            type="submit"
            :disabled="pending || Boolean(interaction) || !text.trim()"
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
