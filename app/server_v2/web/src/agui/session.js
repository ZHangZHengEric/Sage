import { HttpAgent } from '@ag-ui/client'
import { getToken } from '../auth.js'
import { createResumableFetch } from './resume.js'

export function createAguiAgent({ onMessages, onError } = {}) {
  const agent = new HttpAgent({
    url: '/api/agent',
    agentId: 'main',
    fetch: createResumableFetch(),
  })
  agent.subscribe({
    onMessagesChanged({ messages }) {
      onMessages?.([...messages])
    },
    onRunErrorEvent({ event }) {
      onError?.(event.message || 'run failed')
    },
    onRunFailed({ error }) {
      onError?.(error?.message || 'run failed')
    },
  })
  return agent
}

export async function runAgui(agent, { threadId, runId, content }) {
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
    forwardedProps: { agentId: 'main' },
  })
}
