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
  listSkills: () => request('/api/skills'),
  publishSkill: (body) =>
    request('/api/skills', { method: 'POST', body: JSON.stringify(body) }),
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
  threadEvents: (id) => request(`/api/threads/${id}/events`),
  deleteThread: (id) => request(`/api/threads/${id}`, { method: 'DELETE' }),
  adminUsers: () => request('/api/admin/users'),
  adminThreads: () => request('/api/admin/threads'),
  adminModels: () => request('/api/admin/models'),
  adminThreadEvents: (id) => request(`/api/admin/threads/${id}/events`),
  health: () => request('/health'),
}
