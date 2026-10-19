<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { api, isForeign } from '../api.js'
import { createAguiAgent, resumeAgui, runAgui } from '../agui/session.js'
import { decisionErrorText } from '../agui/presentation.js'
import { messagesBeforeLastRun, messagesFromEvents, pendingInteraction } from '../agui/replay.js'
import AguiTranscript from '../components/AguiTranscript.vue'
import WorkspacePanel from '../components/WorkspacePanel.vue'
import AppIcon from '../components/AppIcon.vue'
const workspaceOpen = ref(false)
import { useRoute, useRouter } from 'vue-router'
const route = useRoute(), router = useRouter()
const ready = ref(false)
const initializing = ref(true), configurationLoaded = ref(false), setupFailed = ref(false)

const threads = ref([])
const threadId = ref('')
const text = ref('')
const historyEvents = shallowRef([]), historyOffset = ref(0), historyTotal = ref(0), historyLoading = ref(false)
let historyRevision = 0
let waitingForDecisionReplay = false
// AG-UI owns message objects and clones them with structuredClone. Keep Vue
// proxies out of the SDK; transcript updates replace the entire array.
const messages = shallowRef([])
const pending = ref(false)
const activeRunId = ref(''), streamStarted = ref(false), stopping = ref(false)
const supplementing = ref(false), queuedSupplements = shallowRef([])
const displayMessages = computed(() => [...messages.value, ...queuedSupplements.value.map(item => ({ id: item.messageId, role: 'user', content: item.content, steeringPending: true }))])
const appliedSupplements = new Set()
let supplementAttempt = null
let agentBinding = 0
const error = ref('')
const hasModel = ref(true)
const agents = ref([])
const interaction = ref(null)
const deciding = ref(null), decisionError = ref(''), interactionAnswer = ref(''), transcript = ref(null)
const activeInteraction = computed(() => interaction.value || deciding.value)
watch(activeInteraction, (next, previous) => {
  if (!next || (next.interaction_id ? next.interaction_id !== previous?.interaction_id : next !== previous)) {
    interactionAnswer.value = ''; decisionError.value = ''
    if (next && !readOnly.value) nextTick(() => transcript.value?.focusInteraction())
    else if (!next && previous) nextTick(resizeInput)
  }
})
// Where the Run in flight began. A resumed Run replays from its first event,
// so answering a question means rewinding the transcript back to here first.
const baseline = shallowRef([])
const selectedAgentId = ref(localStorage.getItem('sage.server_v2.agent') || '')
const scroller = ref(null)
const historyEnd = ref(null)
const historyFailed = ref(false)
let historyObserver

watch(historyEnd, (element) => {
  historyObserver?.disconnect()
  if (!element) return
  historyObserver = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting && !historyLoading.value && !historyFailed.value && historyOffset.value < historyTotal.value) {
      void loadHistory()
    }
  }, { root: scroller.value })
  historyObserver.observe(element)
}, { flush: 'post' })
const input = ref(null)
const agent = shallowRef(null)
const agentPackage = shallowRef(null)

const currentThread = computed(() =>
  threads.value.find((item) => item.thread_id === threadId.value)
)
// A fresh unsent conversation has no persisted Session yet. Existing links
// still carry their Session id even while owner metadata is loading.
const workspaceThreadId = computed(() => currentThread.value?.thread_id ||
  (route?.query?.thread === threadId.value ? threadId.value : ''))
const readOnly = computed(() => isForeign(currentThread.value))
const threadTitle = computed(() => currentThread.value?.title || '新对话')
const agentLocked = computed(() => Boolean(currentThread.value?.agent_id || agentPackage.value || pending.value || (!currentThread.value && messages.value.length)))
const selectedAgentName = computed(() => agentPackage.value?.manifest.agents[selectedAgentId.value]?.name ||
  agents.value.find(item => item.id === selectedAgentId.value)?.name || '智能体')
const agentAvailable = computed(() => Boolean(agentPackage.value || agents.value.some(item => item.id === selectedAgentId.value)))
const composerPlaceholder = computed(() => pending.value ? '继续输入…' :
  initializing.value || !agentAvailable.value ? '输入消息…' : `向${selectedAgentName.value}提问…`)
const isStart = computed(() => !currentThread.value && !route?.query?.thread && !messages.value.length && !pending.value && !interaction.value && !historyLoading.value)
const canSend = computed(() => configurationLoaded.value && !initializing.value && !setupFailed.value && !readOnly.value && !historyLoading.value && !historyFailed.value &&
  historyOffset.value >= historyTotal.value && (hasModel.value || Boolean(agentPackage.value)) && agentAvailable.value &&
  !activeInteraction.value && !stopping.value && !supplementing.value &&
  (!pending.value || streamStarted.value) && Boolean(text.value.trim()))

function inputKeydown(event) {
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229 || event.shiftKey || event.altKey) return
  event.preventDefault()
  if (canSend.value) void submit()
}

function newId(prefix) {
  return `${prefix}-${crypto.randomUUID()}`
}

function bindAgent() {
  const binding = ++agentBinding
  agent.value = createAguiAgent({
    agentId: selectedAgentId.value,
    onMessages(next) {
      if (binding !== agentBinding) return
      // Rewind the SDK immediately, but keep the visible transcript while the
      // decision request is still waiting for its first replayed message.
      if (waitingForDecisionReplay && next.length === baseline.value.length && next.every((message, index) => message.id === baseline.value[index]?.id)) return
      waitingForDecisionReplay = false
      messages.value = next
      if (!historyLoading.value) nextTick(() => scroller.value?.scrollTo(0, scroller.value.scrollHeight))
    },
    onInteraction(next) {
      if (binding !== agentBinding) return
      interaction.value = next
      if (!next) deciding.value = null
    },
    onStarted() { if (binding === agentBinding) streamStarted.value = true },
    onSteerApplied(id) {
      if (binding !== agentBinding || !id) return
      appliedSupplements.add(id)
      queuedSupplements.value = queuedSupplements.value.filter(item => item.steerId !== id)
    },
    onError(message) {
      if (binding !== agentBinding) return
      error.value = message
    },
  })
}

async function loadAgents() {
  agents.value = await api.listAgents(false)
  if (!agents.value.some((item) => item.id === selectedAgentId.value)) {
    selectedAgentId.value = agents.value[0]?.id || ''
  }
}

function selectAgent() {
  if (agentLocked.value || readOnly.value || initializing.value) return
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
  const items = await api.listModels(false)
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
  agent.value?.abortRun?.()
  bindAgent()
  waitingForDecisionReplay = false
  ++historyRevision
  pending.value = false; stopping.value = false; streamStarted.value = false; activeRunId.value = ''
  supplementing.value = false; queuedSupplements.value = []; appliedSupplements.clear(); supplementAttempt = null
  agentPackage.value = null
  threadId.value = id; error.value = ''; deciding.value = null; decisionError.value = ''; interactionAnswer.value = ''
  historyLoading.value = false; historyFailed.value = false
  scroller.value?.scrollTo(0, 0)
  historyEvents.value = []; historyOffset.value = 0; historyTotal.value = 0
  messages.value = []; interaction.value = null
  applyThreadAgent(id)
  await loadHistory()
}

async function loadHistory() {
  if (historyLoading.value) return
  const firstPage = historyOffset.value === 0
  historyFailed.value = false
  error.value = ''
  const revision = historyRevision, id = threadId.value
  historyLoading.value = true
  try {
    const page = await api.threadEvents(id, 500, currentThread.value?._owner, historyOffset.value)
    if (revision !== historyRevision) return
    if (firstPage && page.has_package) {
      const bundle = await api.threadPackage(id, currentThread.value?._owner)
      if (revision !== historyRevision) return
      agentPackage.value = bundle
    }
    historyEvents.value = [...historyEvents.value, ...page.events]
    historyOffset.value = page.offset + page.limit; historyTotal.value = page.total
    const events = historyEvents.value, history = messagesFromEvents(events)
    activeRunId.value = events.findLast(event => event.type === 'RUN_STARTED')?.runId || ''
    messages.value = history
    interaction.value = pendingInteraction(events)
    baseline.value = messagesBeforeLastRun(events) || history
    agent.value.threadId = id; agent.value.setMessages(history)
    await nextTick()
    if (firstPage && historyOffset.value >= historyTotal.value) {
      scroller.value?.scrollTo(0, scroller.value.scrollHeight)
    }
  } catch (exc) {
    if (revision === historyRevision) {
      error.value = exc.message
      historyFailed.value = true
    }
  }
  finally { if (revision === historyRevision) historyLoading.value = false }
}

function startNew() {
  agent.value?.abortRun?.()
  bindAgent()
  waitingForDecisionReplay = false
  deciding.value = null; decisionError.value = ''; interactionAnswer.value = ''
  agentPackage.value = null
  ++historyRevision
  pending.value = false; stopping.value = false; streamStarted.value = false; activeRunId.value = ''
  supplementing.value = false; queuedSupplements.value = []; appliedSupplements.clear(); supplementAttempt = null
  historyFailed.value = false
  historyLoading.value = false; historyEvents.value = []; historyOffset.value = 0; historyTotal.value = 0
  if (!agents.value.some(item => item.id === selectedAgentId.value)) {
    selectedAgentId.value = agents.value[0]?.id || ''; bindAgent()
  }
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
  if (!configurationLoaded.value || setupFailed.value || (!agentPackage.value && !hasModel.value) || !agentAvailable.value || readOnly.value || historyLoading.value || historyFailed.value || historyOffset.value < historyTotal.value || !content || pending.value || interaction.value) return
  if (!threadId.value) threadId.value = newId('thread')
  text.value = ''
  nextTick(resizeInput)
  pending.value = true
  streamStarted.value = false; stopping.value = false
  appliedSupplements.clear(); supplementAttempt = null
  const revision = historyRevision
  const runId = newId('run')
  activeRunId.value = runId
  error.value = ''
  const message = { id: crypto.randomUUID(), role: 'user', content }
  baseline.value = [...messages.value, message]
  try {
    await runAgui(agent.value, {
      threadId: threadId.value,
      runId,
      message,
      agentId: selectedAgentId.value,
      agentPackage: agentPackage.value,
    })
    if (revision !== historyRevision) return
    await loadThreads()
    if (route?.query?.package) await router.replace({ path: '/', query: { thread: threadId.value } })
  } catch (exc) {
    if (revision === historyRevision) error.value = exc.message
  } finally {
    if (revision === historyRevision) {
      pending.value = false; stopping.value = false; streamStarted.value = false
      restoreUnappliedSupplements()
      await nextTick()
      scroller.value?.scrollTo(0, scroller.value.scrollHeight)
      input.value?.focus()
    }
  }
}

function restoreUnappliedSupplements() {
  if (interaction.value || !queuedSupplements.value.length) return
  text.value = [...queuedSupplements.value.map(item => item.content), text.value].filter(Boolean).join('\n\n')
  queuedSupplements.value = []
  error.value = '补充内容尚未接收，已放回输入框，可再次发送。'
  nextTick(resizeInput)
}

async function submit() {
  if (!canSend.value) return
  if (!pending.value) return send()
  const draft = text.value, content = draft.trim(), revision = historyRevision
  const runId = activeRunId.value, id = threadId.value
  if (!runId) return
  if (!supplementAttempt || supplementAttempt.runId !== runId || supplementAttempt.content !== content) {
    supplementAttempt = { runId, content, messageId: newId('input') }
  }
  const attempt = supplementAttempt
  supplementing.value = true; error.value = ''
  try {
    const result = await api.steerThreadRun(id, { runId, messageId: attempt.messageId, text: content })
    if (revision !== historyRevision) return
    if (text.value === draft) text.value = ''
    supplementAttempt = null
    if (result.state !== 'applied' && !appliedSupplements.has(result.steer_id)) {
      queuedSupplements.value = [...queuedSupplements.value, { ...attempt, steerId: result.steer_id }]
      if (!pending.value) restoreUnappliedSupplements()
    }
    nextTick(() => { resizeInput(); scroller.value?.scrollTo(0, scroller.value.scrollHeight) })
  } catch (exc) {
    if (revision === historyRevision) error.value = `补充发送失败：${exc.message}`
  } finally {
    if (revision === historyRevision) supplementing.value = false
  }
}

async function stop() {
  if (!pending.value || !streamStarted.value || stopping.value || supplementing.value || activeInteraction.value || readOnly.value || !activeRunId.value) return
  const revision = historyRevision, runId = activeRunId.value
  stopping.value = true; error.value = ''
  try {
    await api.cancelThreadRun(threadId.value, runId)
  } catch (exc) {
    if (revision === historyRevision && pending.value && runId === activeRunId.value) {
      stopping.value = false
      error.value = `停止失败：${exc.message}`
    }
  }
}

async function decide({ decision, payload }) {
  if (readOnly.value || pending.value || !interaction.value || !interaction.value.allowed_decisions?.includes(decision)) return
  if (['submit', 'change_direction'].includes(decision) && (typeof payload?.text !== 'string' || !payload.text.trim())) return
  const asked = interaction.value, revision = historyRevision, shown = messages.value
  deciding.value = asked; decisionError.value = ''
  interaction.value = null
  pending.value = true
  streamStarted.value = false
  error.value = ''
  try {
    // The resumed stream replays the Run from its first event so the client
    // rebuilds item state exactly; rewinding first is what keeps that replay
    // from doubling everything already on screen.
    waitingForDecisionReplay = true
    agent.value.setMessages(baseline.value)
    await resumeAgui(agent.value, {
      threadId: threadId.value,
      runId: newId('run'),
      decision,
      payload,
    })
    if (revision !== historyRevision) return
    try { await loadThreads() } catch (exc) { error.value = exc.message }
  } catch (exc) {
    if (revision !== historyRevision) return
    error.value = exc.message; decisionError.value = decisionErrorText(exc)
    if (waitingForDecisionReplay) { waitingForDecisionReplay = false; agent.value.setMessages(shown) }
    // The question outlived the answer, so it has to come back — otherwise the
    // thread is left waiting with nothing on screen to answer it.
    interaction.value ||= asked
  } finally {
    if (revision === historyRevision) {
      waitingForDecisionReplay = false
      deciding.value = null; pending.value = false; stopping.value = false; streamStarted.value = false
      restoreUnappliedSupplements()
      await nextTick()
      if (interaction.value) transcript.value?.focusInteraction()
      else { scroller.value?.scrollTo(0, scroller.value.scrollHeight); input.value?.focus() }
    }
  }
}

async function initialize() {
  initializing.value = true; configurationLoaded.value = false; setupFailed.value = false; error.value = ''
  bindAgent()
  try {
    await Promise.all([loadThreads(), loadModels(), loadAgents()])
    configurationLoaded.value = true
    if (route?.query?.thread) await openThread(String(route.query.thread))
    else if (route?.query?.new) startNew()
    else if (threads.value[0]) await openThread(threads.value[0].thread_id)
    else startNew()
    if (route?.query?.package) {
      const bundle = await api.package(String(route.query.package))
      const selected = String(route.query.packageAgent || bundle.manifest.entrypoint.agent)
      if (!bundle.manifest.agents[selected]) throw new Error('Package 中没有此智能体')
      bundle.manifest.entrypoint = { agent: selected }
      agentPackage.value = bundle
      selectedAgentId.value = selected
      bindAgent()
      agent.value.threadId = threadId.value
      agent.value.setMessages(messages.value)
      if (!route.query.thread) {
        threadId.value = newId('thread')
        messages.value = []; baseline.value = []; interaction.value = null
        historyEvents.value = []; historyOffset.value = 0; historyTotal.value = 0
        agent.value.setMessages([])
      }
      if (route.query.draft) {
        const key = String(route.query.draft)
        if (!key.startsWith('sage.package-run.')) throw new Error('无效的运行草稿')
        const draft = JSON.parse(sessionStorage.getItem(key) || 'null')
        if (draft) { sessionStorage.removeItem(key); text.value = draft.content; await send() }
      }
    }
    ready.value = true
  } catch (exc) {
    error.value = exc.message
    setupFailed.value = true
  } finally { initializing.value = false }
}
onMounted(initialize)

watch(() => [route?.query?.thread, route?.query?.new], async ([id, fresh]) => {
  if (!ready.value) return
  agent.value?.abortRun?.()
  if (id) await openThread(String(id))
  else if (fresh) startNew()
})

onUnmounted(() => {
  ++historyRevision
  ++agentBinding
  historyObserver?.disconnect()
  agent.value?.abortRun?.()
})
</script>

<template>
  <section class="chat-layout conversation-page" :class="{ 'workspace-open': workspaceOpen }" aria-label="会话" :aria-busy="initializing">
    <div class="thread-root" :class="{ 'conversation-start': isStart }">
      <header class="thread-bar">
        <div v-if="!isStart" class="thread-heading">
          <h1 :title="threadTitle">{{ threadTitle }}</h1>
          <span v-if="readOnly" class="thread-owner">{{ currentThread._owner.username }} · 只读</span>
          <span v-if="readOnly && currentThread.agent_id" class="thread-owner" :title="`智能体：${currentThread.agent_id}`">{{ agentPackage?.manifest.agents[currentThread.agent_id]?.name || currentThread.agent_id }}</span>
        </div>
        <button class="icon-button conversation-workspace" type="button" aria-label="工作空间" :aria-expanded="workspaceOpen" @click="workspaceOpen = !workspaceOpen"><AppIcon name="folder" /></button>
      </header>
      <div class="conversation-body">
        <div ref="scroller" class="thread-viewport">
          <div v-if="isStart" class="conversation-welcome"><img src="/sage_logo.svg" alt="" /><h1>有什么可以帮你？</h1></div>
          <AguiTranscript v-else ref="transcript" :messages="displayMessages" :pending="pending" :interaction="activeInteraction" :read-only="readOnly" :decision-busy="Boolean(deciding)" :decision-error="decisionError" v-model:answer="interactionAnswer" @decide="decide" @open-workspace="workspaceOpen = true" />
          <div v-if="historyOffset < historyTotal && !historyLoading && !historyFailed" ref="historyEnd" class="history-end" aria-hidden="true"></div>
          <p v-if="!isStart && !messages.length && !historyLoading && !pending && !historyFailed && ready" class="conversation-no-messages">{{ readOnly ? '这段会话还没有消息' : '输入消息，继续这段会话' }}</p>
        </div>
        <div v-if="(error && !decisionError) || setupFailed || (!initializing && !readOnly && ((!hasModel && !agentPackage) || !agentAvailable)) || historyLoading" class="conversation-notices">
          <p v-if="historyLoading" role="status">加载会话中…</p>
          <p v-if="!initializing && !hasModel && !readOnly && !agentPackage" class="notice">还没有可用模型，<router-link to="/models">配置模型</router-link>后即可发送。</p>
          <p v-if="!initializing && !agentAvailable && !readOnly" class="notice">{{ agents.length ? '本会话的智能体已不可用，' : '还没有可用智能体，' }}<router-link to="/agents">前往智能体</router-link></p>
          <p v-if="error && !decisionError" class="error" role="alert">{{ error }}</p>
          <button v-if="setupFailed" class="btn secondary" :disabled="initializing" @click="initialize">重新加载</button>
          <button v-else-if="historyFailed" class="btn secondary" @click="loadHistory">重试加载</button>
        </div>
        <footer v-if="!readOnly && historyOffset >= historyTotal && !historyLoading" class="thread-footer">
          <button v-if="activeInteraction" type="button" class="conversation-pending-anchor" :aria-busy="Boolean(deciding)" @click="transcript?.focusInteraction()"><AppIcon :name="activeInteraction.interaction_type === 'approval' ? 'shield' : 'chat'" />{{ deciding ? '正在提交决定…' : activeInteraction.interaction_type === 'approval' ? '查看审批' : '查看问题' }}<AppIcon name="chevron" /></button>
          <form v-else class="composer" @submit.prevent="submit">
            <label class="sr-only" for="chat-input">消息</label>
            <textarea id="chat-input" ref="input" v-model="text" rows="1"
              :placeholder="composerPlaceholder"
              @input="resizeInput" @keydown="inputKeydown" />
            <div class="conversation-composer-tools">
              <label v-if="!initializing && agentAvailable" class="conversation-agent" :class="{ locked: agentLocked }">
                <AppIcon :name="agentLocked ? 'lock' : 'agent'" /><span class="sr-only">智能体</span>
                <span class="conversation-agent-field">
                  <span class="conversation-agent-size" aria-hidden="true">{{ selectedAgentName }}</span>
                <select v-model="selectedAgentId" aria-label="智能体" :disabled="agentLocked || initializing || !agents.length"
                  :title="agentLocked ? '本会话已绑定智能体' : '选择智能体'" @change="selectAgent">
                  <option v-if="agentPackage" :value="selectedAgentId">{{ selectedAgentName }}</option>
                  <option v-for="item in agents" :key="item.id" :value="item.id">{{ item.name || '智能体' }}</option>
                </select>
                  <AppIcon v-if="!agentLocked" name="chevron" class="conversation-agent-chevron" />
                </span>
              </label>
              <button v-if="pending && !text.trim()" class="send" type="button" :disabled="stopping || supplementing || !streamStarted" :aria-label="stopping ? '正在终止' : '终止'" :title="stopping ? '正在终止' : '终止'" @click="stop">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
              </button>
              <button v-else class="send" type="submit" :disabled="!canSend" aria-label="发送" title="发送">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6" /></svg>
              </button>
            </div>
          </form>
        </footer>
      </div>
    </div>
    <WorkspacePanel v-if="workspaceOpen" :key="workspaceThreadId || selectedAgentId" :thread-id="workspaceThreadId" :agent-id="selectedAgentId" :owner="currentThread?._owner" @close="workspaceOpen = false" />
  </section>
</template>

<style scoped>
.history-end { height: 1px; }
.chat-layout { position: relative; }
.chat-layout.workspace-open { grid-template-columns: minmax(0, 1fr) 360px; }
.conversation-body { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.conversation-workspace { margin-left: auto; }
.conversation-page .thread-bar { min-height: 62px; }
.conversation-page .thread-footer { width: min(848px, 100%); padding-bottom: 22px; }
.conversation-page .composer { background: var(--card); border-radius: var(--radius-card); padding: 14px; box-shadow: 0 2px 8px var(--shadow-color); }
.conversation-page .composer textarea { min-height: 54px; padding: 5px 4px; font-size: 14px; }
.conversation-composer-tools { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.conversation-agent { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: calc(100% - 48px); padding: 0 6px; border-radius: var(--radius); color: var(--muted-foreground); }
.conversation-agent:not(.locked):has(select:enabled):hover { background: var(--muted); }
.conversation-agent-field { position: relative; min-width: 0; max-width: 200px; }
.conversation-agent-size { display: block; min-width: 0; padding: 4px 24px 4px 2px; overflow: hidden; white-space: nowrap; font-size: 12px; line-height: 24px; visibility: hidden; }
.conversation-agent > svg { width: 16px; height: 16px; flex-shrink: 0; }
.conversation-agent select { position: absolute; inset: 0; width: 100%; min-width: 0; appearance: none; height: 32px; min-height: 32px; margin: 0; border: 0; box-shadow: none; background: transparent; color: var(--foreground); padding: 4px 22px 4px 2px; font-size: 12px; cursor: pointer; }
.conversation-agent-chevron { position: absolute; top: 50%; right: 4px; width: 12px; height: 12px; transform: translateY(-50%) rotate(90deg); pointer-events: none; }
.conversation-agent select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.conversation-agent.locked select { opacity: 1; cursor: default; color: var(--muted-foreground); }
.conversation-page .send { margin-left: auto; width: 34px; height: 34px; flex-shrink: 0; border-radius: var(--radius); }
.conversation-page .send svg { width: 20px; height: 20px; }
.conversation-start .conversation-body { justify-content: center; overflow-y: auto; padding-bottom: clamp(24px, 8vh, 80px); }
.conversation-start .thread-viewport { flex: 0 0 auto; padding: 14px 24px 27px; overflow: visible; }
.conversation-welcome { display: flex; flex-direction: column; align-items: center; gap: 18px; }
.conversation-welcome img { width: 43px; height: 43px; }
.conversation-welcome h1 { margin: 0; font-size: 27px; font-weight: 550; letter-spacing: -.6px; }
.conversation-start .thread-footer { width: min(738px, 100%); padding-top: 0; padding-bottom: 0; }
.conversation-start .composer textarea { min-height: 69px; }
.conversation-notices { flex-shrink: 0; width: min(800px, 100%); padding: 0 24px 12px; margin: 0 auto; font-size: 12px; }
.conversation-notices p { margin: 0 0 8px; }
.conversation-start .conversation-notices { width: min(738px, 100%); }
.conversation-no-messages { text-align: center; color: var(--muted-foreground); padding: 60px 0; font-size: 13px; }
@media (max-height: 650px) { .conversation-start .conversation-body { justify-content: flex-start; } }
@media (max-width: 900px) { .chat-layout.workspace-open { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 640px) {
  .conversation-page .thread-bar { padding: 8px 14px; min-height: 52px; }
  .conversation-start .conversation-body { justify-content: flex-start; padding-top: 50px; padding-bottom: 26px; }
  .conversation-start .thread-viewport { padding: 0 16px 23px; }
  .conversation-welcome { gap: 14px; }
  .conversation-welcome h1 { font-size: 23px; }
  .conversation-welcome img { width: 38px; height: 38px; }
  .conversation-page .thread-footer { padding-left: 16px; padding-right: 16px; padding-bottom: max(16px, env(safe-area-inset-bottom)); }
  .conversation-start .thread-footer { padding-bottom: 0; }
  .conversation-agent-field { max-width: 190px; }
  .conversation-agent-size { line-height: 32px; }
  .conversation-agent select { height: 40px; min-height: 40px; }
  .conversation-page .send { width: 40px; height: 40px; }
  .conversation-notices { padding-left: 16px; padding-right: 16px; }
}
</style>
