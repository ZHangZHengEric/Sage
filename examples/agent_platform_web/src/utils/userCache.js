/**
 * 用户缓存工具：生成并持久化 user_id，保证同一浏览器稳定不变
 */

const STORAGE_KEY = 'app_user_id'

// 将 ArrayBuffer 转为十六进制字符串
const bufferToHex = (buffer) => {
  const bytes = new Uint8Array(buffer)
  const hex = []
  for (let i = 0; i < bytes.length; i++) {
    const h = bytes[i].toString(16).padStart(2, '0')
    hex.push(h)
  }
  return hex.join('')
}

// 生成浏览器指纹的哈希（稳定）
const generateFingerprintHash = async () => {
  try {
    const parts = [
      navigator.userAgent || 'ua',
      navigator.language || 'lang',
      navigator.platform || 'platform',
      (screen && `${screen.width}x${screen.height}`) || 'screen',
      (screen && screen.colorDepth) || 'depth',
      (Intl && Intl.DateTimeFormat && Intl.DateTimeFormat().resolvedOptions().timeZone) || 'tz',
      typeof localStorage !== 'undefined' ? 'ls' : 'no-ls'
    ]

    const source = parts.join('|')
    const data = new TextEncoder().encode(source)
    if (crypto && crypto.subtle && crypto.subtle.digest) {
      const digest = await crypto.subtle.digest('SHA-256', data)
      return bufferToHex(digest)
    }
  } catch (e) {
    // ignore and fallback below
  }

  // 兜底：使用随机 UUID（同一浏览器首次生成后持久化即可稳定）
  if (crypto && crypto.randomUUID) {
    return crypto.randomUUID().replace(/-/g, '')
  }
  // 进一步兜底：简单随机字符串
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

/**
 * 获取或创建用户ID（持久化至 localStorage）。
 * 返回 Promise<string>
 */
export const getOrCreateUserId = async () => {
  try {
    const existing = localStorage.getItem(STORAGE_KEY)
    if (existing && typeof existing === 'string') {
      return existing
    }
    const fp = await generateFingerprintHash()
    const userId = `u_${fp}`
    localStorage.setItem(STORAGE_KEY, userId)
    return userId
  } catch (e) {
    // 如果 localStorage 不可用或出错，仍然返回一个临时ID
    const fp = await generateFingerprintHash()
    return `u_${fp}`
  }
}

/**
 * 同步获取（仅当已存在于 localStorage 时），否则返回 null。
 */
export const getUserIdSync = () => {
  try {
    const existing = localStorage.getItem(STORAGE_KEY)
    return existing || null
  } catch (e) {
    return null
  }
}