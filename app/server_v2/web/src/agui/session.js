import { HttpAgent } from '@ag-ui/client'
import { getToken } from '../auth.js'
import { createResumableFetch } from './resume.js'

export function messageForAguiError(event, fallback) {
  const code = event?.code || fallback?.code
  if (code === 'server.model_not_configured') {
    return '请先在「模型」页配置模型后再发送'
  }
  return event?.message || fallback?.message || fallback || 'run failed'
}

export function createAguiAgent({ onMessages, onError, agentId = 'main' } = {}) {
  const agent = new HttpAgent({
    url: '/api/agent',
    agentId,
    fetch: createResumableFetch(),
  })
  agent.subscribe({
    onMessagesChanged({ messages }) {
      onMessages?.([...messages])
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

export async function runAgui(agent, { threadId, runId, content, agentId = 'main' }) {
  agent.headers = { Authorization: `Bearer ${getToken()}` }
  agent.threadId = threadId
  agent.addMessage({
    id: crypto.randomUUID(),
    role: 'user',
    content,
  })
  return agent.runAgent({
    runId,
    tools: [],
    context: [],
    forwardedProps: { agentId },
  })
}
