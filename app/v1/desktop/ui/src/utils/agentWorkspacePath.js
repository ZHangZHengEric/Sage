import { homeDir, join } from '@tauri-apps/api/path'

const FILE_PROTOCOL_PATTERN = /^file:\/\//i
const WINDOWS_ABSOLUTE_PATTERN = /^[a-zA-Z]:[\\/]/
const UNIX_ABSOLUTE_PATTERN = /^\//
const URL_SCHEME_PATTERN = /^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//

let cachedHomeDirPromise = null

export const normalizeFileReference = (input) => {
  if (!input) return ''

  let normalized = String(input).trim()

  if (normalized.startsWith('`') && normalized.endsWith('`')) {
    normalized = normalized.slice(1, -1)
  }

  if (FILE_PROTOCOL_PATTERN.test(normalized)) {
    try {
      const u = new URL(normalized)
      if (u.protocol === 'file:') {
        // file:///abs/path → pathname 为 /abs/path；切勿用正则整块删掉 file://，否则会丢掉首字符 /
        normalized = u.pathname || ''
      }
    } catch (error) {
      // 非标准 file URL 时兜底：与 workbench 一致，保留绝对路径前的 /
      normalized = normalized.replace(/^file:\/\/\/?/i, '/')
    }
  }

  try {
    normalized = decodeURIComponent(normalized)
  } catch (error) {
    normalized = normalized.replace(/%20/g, ' ')
  }

  if (/^\/[a-zA-Z]:\//.test(normalized)) {
    normalized = normalized.slice(1)
  }

  if (normalized.startsWith('/sage-workspace/')) {
    normalized = normalized.replace('/sage-workspace/', '/')
  }

  return normalized
}

export const isAbsoluteLocalPath = (input) => {
  const normalized = normalizeFileReference(input)
  if (!normalized) return false
  return WINDOWS_ABSOLUTE_PATTERN.test(normalized) || UNIX_ABSOLUTE_PATTERN.test(normalized)
}

export const isRelativeWorkspacePath = (input) => {
  const normalized = normalizeFileReference(input)
  if (!normalized) return false
  if (isAbsoluteLocalPath(normalized)) return false
  if (URL_SCHEME_PATTERN.test(normalized)) return false
  if (normalized.startsWith('./') || normalized.startsWith('../')) return false
  return /[\\/]/.test(normalized)
}

const getHomeDir = async () => {
  if (!cachedHomeDirPromise) {
    cachedHomeDirPromise = homeDir()
  }
  return cachedHomeDirPromise
}

export const resolveAgentWorkspacePath = async (input, agentId) => {
  const normalized = normalizeFileReference(input)
  if (!normalized) return ''
  if (isAbsoluteLocalPath(normalized)) return normalized
  if (!agentId || !isRelativeWorkspacePath(normalized)) return normalized

  const home = await getHomeDir()
  const segments = normalized.split(/[\\/]+/).filter(Boolean)
  return join(home, '.sage', 'agents', agentId, ...segments)
}
