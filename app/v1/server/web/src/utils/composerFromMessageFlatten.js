import { cleanupAttachmentName, extractAttachmentName } from '@/utils/multimodalContent.js'
import { parseSageSandboxUploadHref } from '@/utils/sageSandboxUploadPath.js'

/**
 * URL 规范化，用于与 image_url block 后跟的 markdown 图片去重。
 */
const urlDedupKey = (s) => {
  if (!s) return ''
  try {
    const u = new URL(String(s))
    u.hash = ''
    return u.href
  } catch {
    return String(s).trim()
  }
}

const sandboxDupKey = (agentId, filename) =>
  `sandbox:${String(agentId || '')}:${String(filename || '')}`

const MD_IMG_RE = /!\[([^\]]*)\]\(([^)]+)\)/g

/**
 * DB/API 个别路径会把用户多模态 content 落成 JSON 字符串；复制或粘贴重建前转成数组再走同一套逻辑。
 *
 * @param {unknown} content 原始 msg.content
 * @returns {string | unknown[] | unknown}
 */
export function normalizeMessageContentForComposer (content) {
  if (typeof content !== 'string') return content
  const t = content.trim()
  if (!t.startsWith('[')) return content
  if (!t.includes('"type"') && !t.includes('"image_url"')) return content
  try {
    const parsed = JSON.parse(t)
    return Array.isArray(parsed) ? parsed : content
  } catch (_) {
    return content
  }
}

const syntheticSandboxMarkdownHref = (agentId, filename) => {
  const aid = encodeURIComponent(String(agentId || '').trim())
  const fname = encodeURIComponent(String(filename || '').trim())
  if (!aid || !fname) return ''
  return `file:///.sage/agents/${aid}/upload_files/${fname}`
}

const pickImageUrlFromPart = (item) => {
  if (!item || item.type !== 'image_url' || typeof item !== 'object') return ''
  let u = ''
  if (item.image_url && typeof item.image_url === 'object') {
    u = item.image_url.url ?? item.image_url.href ?? ''
  }
  if (!u && typeof item.url === 'string') u = item.url
  return String(u || '').trim()
}

/**
 * 将消息的 content（字符串或多模态数组）转成需要填充到输入框的有序段落：
 * - { kind:'text', text }
 * - { kind:'remoteImage', url, preferredName }
 * - { kind:'sageSandboxImage', agentId, filename, preferredName, rawHref }
 *
 * remoteImage.url 一般为 http(s)（剪切板导出为 markdown 图片行）。
 *
 * image_url block 常与紧随其后的 markdown ![](同 url) 重复，按存盘结构与 desktop/web 对齐做去重。
 */
export function flattenMessageForComposerRebuild (content) {
  content = normalizeMessageContentForComposer(content)
  const segments = []

  /** 已作为独立片段发出的图片 URL / 沙箱文件（避免剪切板正文里重复的 ![](...) 或未配对的冗余行触发多次镜像上传） */
  const emittedStandaloneImageKeys = new Set()

  /** @type {Map<string, number>} */
  const markdownDupSkipsLeft = new Map()

  const registerStructuredDupUrl = (u) => {
    const key = urlDedupKey(u)
    if (!key.startsWith('http')) return
    markdownDupSkipsLeft.set(key, (markdownDupSkipsLeft.get(key) || 0) + 1)
  }

  /** @type {Map<string, number>} */
  const sandboxMarkdownSkipsLeft = new Map()

  const registerSandboxDup = (agentId, filename) => {
    const k = sandboxDupKey(agentId, filename)
    sandboxMarkdownSkipsLeft.set(k, (sandboxMarkdownSkipsLeft.get(k) || 0) + 1)
  }

  const tryConsumeStructuredDupMarkdown = (u) => {
    const key = urlDedupKey(u)
    if (!key.startsWith('http')) return false
    const left = markdownDupSkipsLeft.get(key) || 0
    if (left <= 0) return false
    markdownDupSkipsLeft.set(key, left - 1)
    return true
  }

  const tryConsumeSandboxStructuredDupMarkdown = (agentId, filename) => {
    const key = sandboxDupKey(agentId, filename)
    const left = sandboxMarkdownSkipsLeft.get(key) || 0
    if (left <= 0) return false
    sandboxMarkdownSkipsLeft.set(key, left - 1)
    return true
  }

  const appendText = (t) => {
    if (!t) return
    const last = segments[segments.length - 1]
    if (last && last.kind === 'text') last.text += t
    else segments.push({ kind: 'text', text: t })
  }

  /** @returns {boolean} 是否新增了片段（用于仅在「真正有图」时登记 structured→markdown 去重配额） */
  const pushRemoteImage = (url, preferredName) => {
    const u = String(url || '').trim()
    if (!/^https?:\/\//i.test(u)) return false
    const dk = urlDedupKey(u)
    if (!dk.startsWith('http')) return false
    if (emittedStandaloneImageKeys.has(dk)) return false
    emittedStandaloneImageKeys.add(dk)
    const nameHint = preferredName
      ? cleanupAttachmentName(preferredName)
      : extractAttachmentName(u)
    segments.push({
      kind: 'remoteImage',
      url: u,
      preferredName: nameHint || extractAttachmentName(u) || cleanupAttachmentName('图片')
    })
    return true
  }

  const pushSageSandboxImage = (agentId, filename, preferredName, rawHref) => {
    const key = sandboxDupKey(agentId, filename)
    if (emittedStandaloneImageKeys.has(key)) return false
    emittedStandaloneImageKeys.add(key)
    const fromAlt = preferredName ? cleanupAttachmentName(preferredName) : ''
    const fromFile = extractAttachmentName(filename) || cleanupAttachmentName(filename) || cleanupAttachmentName('图片')
    segments.push({
      kind: 'sageSandboxImage',
      agentId,
      filename,
      rawHref: rawHref ?? '',
      preferredName: fromAlt || fromFile
    })
    return true
  }

  const processPlainTextSlice = (text) => {
    if (!text) return
    let pos = 0
    MD_IMG_RE.lastIndex = 0
    let m
    while ((m = MD_IMG_RE.exec(text)) !== null) {
      const before = text.slice(pos, m.index)
      appendText(before)
      pos = MD_IMG_RE.lastIndex

      const alt = (m[1] || '').trim()
      const href = String(m[2] || '').trim()

      if (href.startsWith('attachment://')) {
        appendText(m[0])
        continue
      }
      if (/^https?:\/\//i.test(href)) {
        const consumeDup = tryConsumeStructuredDupMarkdown(href)
        if (!consumeDup) {
          pushRemoteImage(href, alt)
        }
        continue
      }

      const sp = parseSageSandboxUploadHref(href)
      if (sp) {
        const consumeDup = tryConsumeSandboxStructuredDupMarkdown(sp.agentId, sp.filename)
        if (!consumeDup) {
          pushSageSandboxImage(sp.agentId, sp.filename, alt, href)
        }
        continue
      }

      appendText(m[0])
    }
    appendText(text.slice(pos))
  }

  if (content == null || content === '') return []

  if (typeof content === 'string') {
    processPlainTextSlice(content)
    return segments
  }

  if (!Array.isArray(content)) return []

  for (const item of content) {
    if (!item || typeof item !== 'object') continue

    if (item.type === 'image_url') {
      const u = pickImageUrlFromPart(item)
      if (!u) continue
      const sandbox = parseSageSandboxUploadHref(u)
      if (sandbox) {
        const added = pushSageSandboxImage(sandbox.agentId, sandbox.filename, '', u)
        if (added) {
          registerSandboxDup(sandbox.agentId, sandbox.filename)
        }
        continue
      }

      const addedRemote = pushRemoteImage(u, '')
      if (addedRemote) {
        registerStructuredDupUrl(u)
      }
      continue
    }

    if (item.type === 'text' && typeof item.text === 'string') {
      processPlainTextSlice(item.text)
    }
  }

  return segments
}

/** 导出到剪贴板：保留正文顺序并在图片槽位插入 ![](url)，不写入输入框。 */
export function buildClipboardTextFromMessageContent (content) {
  const segments = flattenMessageForComposerRebuild(content)
  let out = ''
  for (const seg of segments) {
    if (seg.kind === 'text') out += seg.text ?? ''
    else if (seg.kind === 'remoteImage') out += `\n![](${seg.url})\n`
    else if (seg.kind === 'sageSandboxImage') {
      const href = String(seg.rawHref || '').trim()
      if (href) {
        out += `\n![](${href})\n`
      } else {
        const synth = syntheticSandboxMarkdownHref(seg.agentId, seg.filename)
        if (synth) out += `\n![](${synth})\n`
      }
    }
  }
  out = String(out ?? '').trim()
  return out
}
