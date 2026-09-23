import { HttpAgent } from '@ag-ui/client'
import { getToken } from '../auth.js'
import { createResumableFetch } from './resume.js'

const AGENT_URL = '/api/agent'
const INTERACTION_CLOSED = new Set([
  'sage.interaction.resolved',
  'sage.interaction.expired',
  'sage.interaction.cancelled',
])

class SageHttpAgent extends HttpAgent {
  /** The answer the next run carries, or null when it starts fresh work. */
  answer = null

  requestInit(input) {
    const init = super.requestInit(input)
    if (!this.answer) return init
    // The resume endpoint takes an answer, not a Run: which of the pending
    // question's decisions this is, plus the run id of the stream it opens.
    // Which Run is waiting is the thread's to know, not the client's to say.
    return { ...init, body: JSON.stringify({ runId: input.runId, ...this.answer }) }
  }
}

export function messageForAguiError(event, fallback) {
  const code = event?.code || fallback?.code
  if (code === 'server.model_not_configured') {
    return '请先在「模型」页配置模型后再发送'
  }
  return event?.message || fallback?.message || fallback || 'run failed'
}

export function createAguiAgent({ onMessages, onError, onInteraction, agentId = 'main' } = {}) {
  const agent = new SageHttpAgent({
    url: AGENT_URL,
    agentId,
    fetch: createResumableFetch(),
  })
  agent.subscribe({
    onMessagesChanged({ messages }) {
      onMessages?.([...messages])
    },
    onCustomEvent({ event }) {
      if (event?.name === 'sage.interaction.requested') {
        onInteraction?.(event.value || null)
      } else if (INTERACTION_CLOSED.has(event?.name)) {
        onInteraction?.(null)
      }
    },
    onRunErrorEvent({ event }) {
      onError?.(messageForAguiError(event))
    },
    onRunFailed({ error }) {
      onError?.(messageForAguiError(error, error))
    },
  })
  return agent
}

export async function runAgui(agent, { threadId, runId, message, agentId = 'main' }) {
  agent.headers = { Authorization: `Bearer ${getToken()}` }
  agent.threadId = threadId
  agent.addMessage(message)
  return agent.runAgent({
    runId,
    tools: [],
    context: [],
    forwardedProps: { agentId },
  })
}

export async function resumeAgui(agent, { threadId, runId, decision, payload = {} }) {
  agent.headers = { Authorization: `Bearer ${getToken()}` }
  agent.threadId = threadId
  agent.url = `/api/threads/${encodeURIComponent(threadId)}/resume`
  agent.answer = { decision, payload }
  try {
    return await agent.runAgent({ runId, tools: [], context: [] })
  } finally {
    agent.url = AGENT_URL
    agent.answer = null
  }
}
