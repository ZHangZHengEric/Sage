/**
 * Agent 工作区文件一律走后端 HTTP（与 VideoRenderer stream 一致），
 * 避免 WebView 直接读盘路径带来的权限与路径拼接问题。
 */
import { taskAPI } from '@/api/task.js'

/**
 * 从绝对路径解析 agentId 与工作区内相对路径。
 * 支持 macOS/Linux 与 Windows 路径规范化。
 * @param {string} input
 * @returns {{ agentId: string, relativePath: string } | null}
 */
export function parseAgentWorkspaceAbsolutePath(input) {
  if (input == null || input === '') return null
  let p = String(input).trim().replace(/^file:\/\//i, '')
  const norm = p.replace(/\\/g, '/')
  const needle = '/.sage/agents/'
  const idx = norm.indexOf(needle)
  if (idx === -1) return null
  const tail = norm.slice(idx + needle.length)
  const slash = tail.indexOf('/')
  if (slash === -1) return null
  const agentId = tail.slice(0, slash)
  const relativePath = tail.slice(slash + 1)
  if (!agentId || !relativePath) return null
  return { agentId, relativePath }
}

export function isAgentWorkspaceAbsolutePath(input) {
  return parseAgentWorkspaceAbsolutePath(input) != null
}

export async function readWorkspaceBlobViaBackend(agentId, relativePath) {
  return taskAPI.downloadFile(agentId, relativePath)
}

export async function readWorkspaceTextViaBackend(agentId, relativePath) {
  const blob = await taskAPI.downloadFile(agentId, relativePath)
  return blob.text()
}

export async function readWorkspaceArrayBufferViaBackend(agentId, relativePath) {
  const blob = await taskAPI.downloadFile(agentId, relativePath)
  return blob.arrayBuffer()
}

/** @returns {Promise<string>} blob: URL，调用方须在适当时机 revoke */
export async function createWorkspaceBlobUrlViaBackend(agentId, relativePath) {
  const blob = await taskAPI.downloadFile(agentId, relativePath)
  return URL.createObjectURL(blob)
}

/** `.sage/agents/...` 走后端；其它路径仍用 Tauri 读盘 */
export async function readLocalOrWorkspaceUint8Array(inputPath) {
  if (!inputPath) throw new Error('empty path')
  const clean = String(inputPath).trim().replace(/^file:\/\//i, '')
  const parsed = parseAgentWorkspaceAbsolutePath(clean)
  if (parsed) {
    const ab = await readWorkspaceArrayBufferViaBackend(parsed.agentId, parsed.relativePath)
    return new Uint8Array(ab)
  }
  const { readFile } = await import('@tauri-apps/plugin-fs')
  return readFile(clean)
}

/** `.sage/agents/...` 走后端；其它路径仍用 Tauri 读盘 */
export async function readLocalOrWorkspaceText(inputPath) {
  if (!inputPath) throw new Error('empty path')
  const clean = String(inputPath).trim().replace(/^file:\/\//i, '')
  const parsed = parseAgentWorkspaceAbsolutePath(clean)
  if (parsed) {
    return readWorkspaceTextViaBackend(parsed.agentId, parsed.relativePath)
  }
  const { readTextFile } = await import('@tauri-apps/plugin-fs')
  return readTextFile(clean)
}
