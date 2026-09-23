import { clearSession, getToken } from './auth.js'

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(path, { ...options, headers })
  const payload = await response.json().catch(() => ({}))
  if (response.status === 401 && !path.startsWith('/api/auth/')) {
    clearSession()
    if (window.location.pathname !== '/login') {
      window.location.assign('/login')
    }
  }
  if (!response.ok) {
    throw new Error(payload.message || `HTTP ${response.status}`)
  }
  return payload.data
}

export const api = {
  packageSchema: () => request('/api/agent-packages/schema'),
  packageTemplate: (agentId = '') => request(`/api/agent-packages/template${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`),
  packages: (offset = 0) => request(`/api/agent-packages?limit=50&offset=${offset}`),
  package: (ref) => request(`/api/agent-packages/${encodeURIComponent(ref)}`),
  savePackage: (bundle) => request('/api/agent-packages', { method: 'POST', body: JSON.stringify(bundle) }),
  validatePackage: (bundle) => request('/api/agent-packages/validate', { method: 'POST', body: JSON.stringify({ bundle, readiness: true }) }),
  activatePackage: (ref, expected_ref) => request(`/api/agent-packages/${encodeURIComponent(ref)}/activate`, { method: 'POST', body: JSON.stringify({ expected_ref }) }),
  forkPackage: (ref, package_id, version) => request(`/api/agent-packages/${encodeURIComponent(ref)}/fork`, { method: 'POST', body: JSON.stringify({ package_id, version }) }),
  packageRuns: (offset = 0) => request(`/api/agent-packages/runs?limit=50&offset=${offset}`),
  runPackage: (body) => request('/api/agent-packages/runs', { method: 'POST', body: JSON.stringify(body) }),
  packageEvents: (operation, cursor = 0) => request(`/api/agent-packages/runs/${encodeURIComponent(operation)}/events?after_sequence=${cursor}`),
  packageRun: (operation) => request(`/api/agent-packages/runs/${encodeURIComponent(operation)}`),
  controlPackageRun: (operation, body) => request(`/api/agent-packages/runs/${encodeURIComponent(operation)}/control`, { method: 'POST', body: JSON.stringify(body) }),
  login: (username, password) =>
    request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  register: (username, password) =>
    request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  session: () => request('/api/auth/session'),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  listModels: () => request('/api/models'),
  saveModel: (body) =>
    request('/api/models', { method: 'POST', body: JSON.stringify(body) }),
  deleteModel: (id) => request(`/api/models/${id}`, { method: 'DELETE' }),
  listTools: () => request('/api/tools'),
  listAgents: () => request('/api/agents'),
  getAgent: (id) => request(`/api/agents/${id}`),
  createAgent: (body) =>
    request('/api/agents', { method: 'POST', body: JSON.stringify(body) }),
  updateAgent: (id, body) =>
    request(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteAgent: (id) => request(`/api/agents/${id}`, { method: 'DELETE' }),
  listMcp: () => request('/api/mcp'),
  createMcp: (body) =>
    request('/api/mcp', { method: 'POST', body: JSON.stringify(body) }),
  updateMcp: (name, body) =>
    request(`/api/mcp/${name}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteMcp: (name) => request(`/api/mcp/${name}`, { method: 'DELETE' }),
  refreshMcp: (name) => request(`/api/mcp/${name}/refresh`, { method: 'POST' }),
  listA2aAgents: () => request('/api/a2a-agents'),
  createA2aAgent: (body) =>
    request('/api/a2a-agents', { method: 'POST', body: JSON.stringify(body) }),
  updateA2aAgent: (name, body) =>
    request(`/api/a2a-agents/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteA2aAgent: (name) =>
    request(`/api/a2a-agents/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  refreshA2aAgent: (name) =>
    request(`/api/a2a-agents/${encodeURIComponent(name)}/refresh`, { method: 'POST' }),
  listSkills: () => request('/api/skills'),
  publishSkill: (body) =>
    request('/api/skills', { method: 'POST', body: JSON.stringify(body) }),
  uploadSkills: (files) => {
    const body = new FormData()
    for (const file of files) body.append('files', file)
    return request('/api/skills/upload', { method: 'POST', body })
  },
  getSkill: (id) => request(`/api/skills/${id}`),
  updateSkill: (id, body) =>
    request(`/api/skills/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteSkill: (id) => request(`/api/skills/${id}`, { method: 'DELETE' }),
  listAgentSkills: (agentId) => request(`/api/agents/${agentId}/skills`),
  bindAgentSkills: (agentId, names) =>
    request(`/api/agents/${agentId}/skills`, {
      method: 'PUT',
      body: JSON.stringify({ names }),
    }),
  writeWorkspaceSkill: (name, content) =>
    request(`/api/workspace/skills/${name}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  listThreads: () => request('/api/threads'),
  threadEvents: (id, limit = 500) => request(`/api/threads/${id}/events?limit=${limit}`),
  deleteThread: (id) => request(`/api/threads/${id}`, { method: 'DELETE' }),
  adminUsers: () => request('/api/admin/users'),
  adminThreads: () => request('/api/admin/threads'),
  adminModels: () => request('/api/admin/models'),
  adminThreadEvents: (id, limit = 500) => request(`/api/admin/threads/${id}/events?limit=${limit}`),
  health: () => request('/health'),
}
