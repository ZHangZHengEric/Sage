import { clearSession, getToken, getUser, isAdmin } from './auth.js'

async function request(path, options = {}, binary = false) {
  const headers = { ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(path, { ...options, headers })
  const payload = binary && response.ok ? null : await response.json().catch(() => ({}))
  if (response.status === 401 && !path.startsWith('/api/auth/')) {
    clearSession()
    if (window.location.pathname !== '/login') {
      window.location.assign('/login')
    }
  }
  if (!response.ok) {
    throw new Error(payload.message || `HTTP ${response.status}`)
  }
  if (binary) {
    const disposition = response.headers.get('Content-Disposition') || ''
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    return { blob: await response.blob(), filename: encoded ? decodeURIComponent(encoded) : 'download' }
  }
  return payload.data
}

export function isForeign(item) {
  return Boolean(item?._owner && item._owner.user_id !== getUser()?.user_id)
}

function read(path, owner) {
  return request(path, owner ? { headers: { 'X-Sage-View-User': owner.user_id } } : {})
}

let usersRequest = null
function usersForView() {
  if (!usersRequest) usersRequest = request('/api/admin/users').finally(() => { usersRequest = null })
  return usersRequest
}

async function list(path, all = true) {
  if (!all || !isAdmin()) return request(path)
  const users = await usersForView()
  const items = []
  for (const owner of users) {
    const page = await read(path, owner)
    const rows = Array.isArray(page) ? page : page.items
    for (const item of rows) {
      // System skills appear once; admin's visible skill list also includes
      // other owners, who are read in their own scope below.
      if (path === '/api/skills' && item.owner_user_id !== owner.user_id) continue
      items.push({ ...item, _owner: owner })
    }
  }
  return items
}

export const api = {
  workspaceFiles: (path = '', owner, threadId = '', agentId = '') => read(`/api/workspace/files?path=${encodeURIComponent(path)}${threadId ? `&thread_id=${encodeURIComponent(threadId)}` : `&agent_id=${encodeURIComponent(agentId)}`}`, threadId ? undefined : owner),
  workspaceDownload: (path = '', owner, threadId = '', agentId = '') => request(`/api/workspace/download?path=${encodeURIComponent(path)}${threadId ? `&thread_id=${encodeURIComponent(threadId)}` : `&agent_id=${encodeURIComponent(agentId)}`}`, !threadId && owner ? { headers: { 'X-Sage-View-User': owner.user_id } } : {}, true),
  downloadSession: id => request(`/api/threads/${encodeURIComponent(id)}/download`, {}, true),
  executionPolicy: () => request('/api/auth/execution-policy'),
  saveExecutionPolicy: (body) => request('/api/auth/execution-policy',
    { method: 'PUT', body: JSON.stringify(body) }),
  listKeys: () => list('/api/keys'),
  createKey: (body) => request('/api/keys', { method: 'POST', body: JSON.stringify(body) }),
  revokeKey: (id) => request(`/api/keys/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  packageSchema: () => request('/api/agent-packages/schema'),
  packageTemplate: (agentId = '') => request(`/api/agent-packages/template${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`),
  packages: (offset = 0) => list(`/api/agent-packages?limit=50&offset=${offset}`),
  package: (ref, owner) => read(`/api/agent-packages/${encodeURIComponent(ref)}`, owner),
  savePackage: (bundle) => request('/api/agent-packages', { method: 'POST', body: JSON.stringify(bundle) }),
  validatePackage: (bundle) => request('/api/agent-packages/validate', { method: 'POST', body: JSON.stringify({ bundle, readiness: true }) }),
  activatePackage: (ref, expected_ref) => request(`/api/agent-packages/${encodeURIComponent(ref)}/activate`, { method: 'POST', body: JSON.stringify({ expected_ref }) }),
  forkPackage: (ref, package_id, version) => request(`/api/agent-packages/${encodeURIComponent(ref)}/fork`, { method: 'POST', body: JSON.stringify({ package_id, version }) }),
  packageRuns: (offset = 0) => list(`/api/agent-packages/runs?limit=50&offset=${offset}`),
  runPackage: (body) => request('/api/agent-packages/runs', { method: 'POST', body: JSON.stringify(body) }),
  packageEvents: (operation, cursor = 0, owner) => read(`/api/agent-packages/runs/${encodeURIComponent(operation)}/events?after_sequence=${cursor}`, owner),
  packageRun: (operation, owner) => read(`/api/agent-packages/runs/${encodeURIComponent(operation)}`, owner),
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
  listModels: (all = true) => list('/api/models', all),
  getModel: (id, owner) => read(`/api/models/${encodeURIComponent(id)}`, owner),
  saveModel: (body) =>
    request('/api/models', { method: 'POST', body: JSON.stringify(body) }),
  deleteModel: (id) => request(`/api/models/${id}`, { method: 'DELETE' }),
  listTools: () => request('/api/tools'),
  listAgents: (all = true) => list('/api/agents', all),
  getAgent: (id, owner) => read(`/api/agents/${id}`, owner),
  createAgent: (body) =>
    request('/api/agents', { method: 'POST', body: JSON.stringify(body) }),
  updateAgent: (id, body) =>
    request(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteAgent: (id) => request(`/api/agents/${id}`, { method: 'DELETE' }),
  listMcp: (all = true) => list('/api/mcp', all),
  createMcp: (body) =>
    request('/api/mcp', { method: 'POST', body: JSON.stringify(body) }),
  updateMcp: (name, body) =>
    request(`/api/mcp/${name}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteMcp: (name) => request(`/api/mcp/${name}`, { method: 'DELETE' }),
  refreshMcp: (name) => request(`/api/mcp/${name}/refresh`, { method: 'POST' }),
  listA2aAgents: (all = true) => list('/api/a2a-agents', all),
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
  listSkills: (all = true) => list('/api/skills', all),
  publishSkill: (body) =>
    request('/api/skills', { method: 'POST', body: JSON.stringify(body) }),
  uploadSkills: (files) => {
    const body = new FormData()
    for (const file of files) body.append('files', file)
    return request('/api/skills/upload', { method: 'POST', body })
  },
  getSkill: (id, owner) => read(`/api/skills/${id}`, owner),
  skillFiles: (id, owner) => read(`/api/skills/${encodeURIComponent(id)}/files`, owner),
  skillFile: (id, path, owner) => request(
    `/api/skills/${encodeURIComponent(id)}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
    owner ? { headers: { 'X-Sage-View-User': owner.user_id } } : {},
    true,
  ),
  updateSkill: (id, body) =>
    request(`/api/skills/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteSkill: (id) => request(`/api/skills/${id}`, { method: 'DELETE' }),
  listAgentSkills: (agentId, owner) => read(`/api/agents/${agentId}/skills`, owner),
  bindAgentSkills: (agentId, names) =>
    request(`/api/agents/${agentId}/skills`, {
      method: 'PUT',
      body: JSON.stringify({ names }),
    }),
  writeWorkspaceSkill: (name, content, agentId) =>
    request(`/api/workspace/skills/${name}?agent_id=${encodeURIComponent(agentId)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  listThreads: async () => isAdmin() ? (await request('/api/admin/threads')).map(item => ({ ...item, _owner: { user_id: item.user_id, username: item.username } })) : request('/api/threads'),
  threadEvents: (id, limit = 500, owner, offset) => read(`/api/threads/${encodeURIComponent(id)}/events?limit=${limit}${offset === undefined ? "" : `&offset=${offset}`}`, owner),
  deleteThread: (id) => request(`/api/threads/${id}`, { method: 'DELETE' }),
  adminUsers: () => request('/api/admin/users'),
  health: () => request('/health'),
}
