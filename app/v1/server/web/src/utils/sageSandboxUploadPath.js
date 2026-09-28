/**
 * 粘贴 / 会话中的 markdown 形如：![](.../.sage/agents/<agent_id>/upload_files/<filename>)
 * 浏览器无法用本地绝对路径抓取，需在 flatten 阶段识别并由 sidecar/server 读取沙箱既有文件。
 */
const SANDBOX_MARKDOWN_UPLOAD_RE =
  /\.sage\/agents\/([^/\\]+)\/upload_files\/([^)\s]+)/

/**
 * @param {string} href markdown 链接目标
 * @returns {{ agentId: string, filename: string } | null}
 */
export function parseSageSandboxUploadHref (href) {
  const s = String(href ?? '').trim()
  const m = s.match(SANDBOX_MARKDOWN_UPLOAD_RE)
  if (!m) return null
  const agentId = String(m[1] || '').trim()
  let filename = String(m[2] || '').trim()
  filename = filename.split(/[?#]/)[0].trim()
  if (/%[0-9a-f]{2}/i.test(filename)) {
    try {
      filename = decodeURIComponent(filename)
    } catch (_) { /* noop */ }
  }
  if (!agentId || !filename) return null
  if (filename.includes('..')) return null
  if (filename.includes('/') || filename.includes('\\')) return null
  return { agentId, filename }
}
