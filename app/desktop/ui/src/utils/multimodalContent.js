/**
 * 多模态内容（输入框附件 / 气泡渲染）相关工具。
 *
 * - 输入框中以 markdown 图片语法 `![name](attachment://<id>)` 作为占位符；
 *   图片文件用此语法，其他文件可使用 `[name](attachment://<id>)`（无前导 `!`）。
 * - 提交时按出现位置切片成有序的 multimodal content 数组。
 * - 多模态开启时，每个图片为：先 `image_url`，再紧跟 `![name](url)`；「以上图片引用…」由 sagents 仅在请求 LLM 时注入，不写入存盘。
 * - 气泡渲染按数组顺序逐项展示；`getRenderableContentItems` 仍按 URL 去重 image_url。
 */

const ATTACHMENT_PLACEHOLDER_RE = /(!?)\[([^\]]*)\]\(attachment:\/\/([^)]+)\)/g

/** 转义正则中的特殊字符。 */
const escapeRegExp = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** 清理 OSS 自动追加的时间戳后缀，让附件文件名更可读。 */
export const cleanupAttachmentName = (name) => {
  if (!name) return '文件'
  let cleanName = String(name)
  cleanName = cleanName.replace(/_\d{14}\.([^.]+)$/, '.$1')
  cleanName = cleanName.replace(/_\d{14}_/, '_')
  return cleanName
}

/** 生成一个用于 textarea 的占位符文本（图片用 markdown 图片语法）。 */
export const buildAttachmentPlaceholder = (file) => {
  if (!file || file.id == null) return ''
  const name = cleanupAttachmentName(file.name)
  const prefix = file.type === 'image' ? '!' : ''
  return `${prefix}[${name}](attachment://${file.id})`
}

/** 从一个完整 URL 中取出最后一段文件名（用作 markdown alt，确保与 URL 末段完全一致）。 */
const extractUrlTailName = (url) => {
  if (!url) return ''
  try {
    const u = new URL(url, 'http://localhost')
    const last = decodeURIComponent(u.pathname.split('/').pop() || '')
    return last || ''
  } catch {
    const s = String(url).split('?')[0].split('#')[0]
    const last = s.split('/').pop() || ''
    return last
  }
}

/**
 * 从输入框文本中移除某个附件的占位符（一并清掉相邻的换行，避免留下空行）。
 */
export const removeAttachmentPlaceholder = (text, fileId) => {
  if (!text || fileId == null) return text || ''
  const idPart = escapeRegExp(String(fileId))
  const re = new RegExp(
    `\\n?[ \\t]*!?\\[[^\\]]*\\]\\(attachment:\\/\\/${idPart}\\)[ \\t]*\\n?`,
    'g'
  )
  return text.replace(re, '\n').replace(/\n{3,}/g, '\n\n').replace(/^\n+/, '')
}

/**
 * 检测某个附件 id 是否在文本中已有占位符。
 */
export const textHasAttachmentPlaceholder = (text, fileId) => {
  if (!text || fileId == null) return false
  const idPart = escapeRegExp(String(fileId))
  const re = new RegExp(`!?\\[[^\\]]*\\]\\(attachment:\\/\\/${idPart}\\)`)
  return re.test(text)
}

/**
 * 按 textarea 中占位符出现的顺序，构建 multimodal content 数组与纯文本回退。
 *
 * @param {string} rawText - textarea 原始文本（可能含占位符）。
 * @param {Array} files - 已上传完成的附件列表（必须含 id, url, name, type）。
 * @param {Object} [options]
 * @param {boolean} [options.multimodalEnabled=true] - 是否开启多模态（影响图片是否拆为 image_url part）。
 * @param {string} [options.headPrefix=''] - 整体头部前缀（如 <skill>...</skill>、<enable_plan>...</enable_plan>）。
 * @returns {{ contentArray: Array, plainText: string }}
 */
export const buildOrderedMultimodalContent = (rawText, files = [], options = {}) => {
  const { multimodalEnabled = true, headPrefix = '' } = options

  const filesById = new Map()
  for (const f of files || []) {
    if (f && f.id != null && f.url) filesById.set(String(f.id), f)
  }

  const items = []
  const usedIds = new Set()
  let plainText = ''

  const pushText = (text) => {
    if (!text) return
    if (items.length > 0 && items[items.length - 1].type === 'text') {
      items[items.length - 1].text += text
    } else {
      items.push({ type: 'text', text })
    }
  }

  const text = String(rawText || '')
  ATTACHMENT_PLACEHOLDER_RE.lastIndex = 0
  let lastIndex = 0
  let m
  while ((m = ATTACHMENT_PLACEHOLDER_RE.exec(text)) !== null) {
    const before = text.slice(lastIndex, m.index)
    pushText(before)
    plainText += before

    const filename = m[2] || ''
    const id = m[3]
    const file = filesById.get(String(id))
    if (file && file.url) {
      usedIds.add(String(id))
      // 让 markdown alt 与最终 URL 末段保持一致：优先用上传后服务端真实文件名（file.name 已在上传完成时刷新成 filename），
      // 退化时再用占位符里的旧名字 / 清洗版本，避免后端 LLM 看到 alt 与链接不同导致疑惑。
      const urlTailName = extractUrlTailName(file.url)
      const cleanName = urlTailName || file.name || cleanupAttachmentName(filename || '') || '文件'
      const realImage = `![${cleanName}](${file.url})`
      const realLink = `[${cleanName}](${file.url})`

      if (file.type === 'image') {
        if (multimodalEnabled) {
          // image_url 在前；说明行由 sagents 在请求 LLM 前注入，不写入存盘 content。
          items.push({ type: 'image_url', image_url: { url: file.url } })
          pushText(realImage)
          plainText += realImage
        } else {
          pushText(realImage)
          plainText += realImage
        }
      } else {
        pushText(realLink)
        plainText += realLink
      }
    } else {
      // 占位符无对应附件（上传中或已被移除）：从提交内容中静默剔除，
      // 输入框中的占位符仍可见，避免用户消息中残留 attachment:// 字面量。
    }

    lastIndex = ATTACHMENT_PLACEHOLDER_RE.lastIndex
  }

  const tail = text.slice(lastIndex)
  pushText(tail)
  plainText += tail

  // 头部统一前缀（<skill>/<enable_plan>），保证落在第一个 text part 的最前。
  if (headPrefix) {
    if (items.length === 0 || items[0].type !== 'text') {
      items.unshift({ type: 'text', text: headPrefix })
    } else {
      items[0].text = headPrefix + items[0].text
    }
    plainText = headPrefix + plainText
  }

  // 兜底：未在文本中出现的附件追加到末尾
  const orphans = []
  for (const f of files || []) {
    if (f && f.id != null && f.url && !usedIds.has(String(f.id))) {
      orphans.push(f)
    }
  }
  if (orphans.length > 0) {
    const sep = plainText && !plainText.endsWith('\n') ? '\n\n' : ''
    let firstOrphan = true
    for (const f of orphans) {
      const cleanName = extractUrlTailName(f.url) || f.name || cleanupAttachmentName(f.name || '')
      const lead = firstOrphan ? sep : '\n'
      firstOrphan = false
      if (f.type === 'image') {
        const realImage = `![${cleanName}](${f.url})`
        if (multimodalEnabled) {
          items.push({ type: 'image_url', image_url: { url: f.url } })
          const t = `${lead}${realImage}`
          pushText(t)
          plainText += t
        } else {
          const t = `${lead}${realImage}`
          pushText(t)
          plainText += t
        }
      } else {
        const t = `${lead}[${cleanName}](${f.url})`
        pushText(t)
        plainText += t
      }
    }
  }

  // 清理：去掉空的 text part
  const cleaned = items.filter(it =>
    !(it.type === 'text' && (!it.text || !it.text.trim().length))
  )

  return { contentArray: cleaned, plainText }
}

/**
 * 检测某段文本中是否已包含某个 url 的 markdown 图片引用。
 */
export const textHasMarkdownImageRefForUrl = (text, url) => {
  if (!text || !url) return false
  const re = new RegExp(`!\\[[^\\]]*\\]\\(${escapeRegExp(url)}\\)`)
  return re.test(text)
}

/**
 * 把消息 content 转成"按顺序渲染"的项列表（统一字符串/数组两种来源）。
 * 返回项形如：
 *   { type: 'text', text }
 *   { type: 'image_url', url }
 *
 * 渲染策略：
 * - 全文拼接后若某 URL 已有对应 markdown 图片语法，则渲染时省略重复的 image_url 网格；
 * - 前端渲染走 MarkdownRenderer：它本身已支持本地路径/http 图片，
 *   因此当某个 image_url 的 url 已被 text 中的 markdown 图片引用覆盖时，
 *   渲染层直接丢弃该 image_url part（避免重复显示，也免去自己再做 asset:// 转换）。
 * - 没有对应 markdown 引用的孤立 image_url 才保留，作为兜底渲染。
 */
export const getRenderableContentItems = (content) => {
  if (content == null || content === '') return []
  if (typeof content === 'string') {
    return content.length > 0 ? [{ type: 'text', text: content }] : []
  }
  if (!Array.isArray(content)) return []
  const items = []
  for (const item of content) {
    if (!item || typeof item !== 'object') continue
    if (item.type === 'text' && typeof item.text === 'string') {
      if (!item.text) continue
      items.push({ type: 'text', text: item.text })
    } else if (item.type === 'image_url' && item.image_url?.url) {
      items.push({ type: 'image_url', url: item.image_url.url })
    }
  }

  const allText = items.filter(it => it.type === 'text').map(it => it.text).join('\n')
  return items.filter(it => {
    if (it.type !== 'image_url') return true
    return !textHasMarkdownImageRefForUrl(allText, it.url)
  })
}

/**
 * 老格式判断：图片 part 集中在末尾、未与 text 交错。
 * 用于决定是否走"老气泡渲染（文本气泡 + 图片网格）"。
 */
export const isLegacyMultimodalLayout = (items) => {
  let seenImage = false
  for (const it of items) {
    if (it.type === 'image_url') {
      seenImage = true
    } else if (it.type === 'text' && seenImage) {
      return false
    }
  }
  return true
}

/** 从附件 URL 推导一个用于显示的文件名。 */
export const extractAttachmentName = (url) => {
  if (!url) return ''
  try {
    const u = new URL(url, 'http://localhost')
    const last = decodeURIComponent(u.pathname.split('/').pop() || '')
    return cleanupAttachmentName(last) || ''
  } catch {
    const s = String(url).split('?')[0]
    const last = s.split('/').pop() || ''
    return cleanupAttachmentName(last) || ''
  }
}

/** 简单从 URL 推断是否为图片。 */
export const isImageUrl = (url) => {
  if (!url) return false
  const ext = (url.split('?')[0].split('.').pop() || '').toLowerCase()
  return ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'].includes(ext)
}
