import { load as loadYaml } from 'js-yaml'

const QUESTIONNAIRE_TAGS = ['sage-questionnaire', 'questionnaire']
const RESPONSE_TAGS = QUESTIONNAIRE_TAGS.map((tag) => `${tag}-response`)
const ARTIFACT_TAGS = ['movo-artifacts', 'ling-artifacts', 'sage-artifacts', 'artifacts']
const DEFAULT_UI_TEXT = {
  other: '其他',
  answerTitle: '问卷回答',
  questionFallback: '问题',
  unanswered: '未填写',
  unselected: '未选择',
  answerSeparator: '：',
  listSeparator: '、',
}

const TAG_PATTERN = new RegExp(
  `<(${[...QUESTIONNAIRE_TAGS, ...RESPONSE_TAGS, ...ARTIFACT_TAGS].join('|')})(\\s[^>]*)?>([\\s\\S]*?)<\\\\?/\\1\\s*>`,
  'gi'
)
const BASIC_HTML_ENTITIES = [
  [/&quot;/g, '"'],
  [/&#34;/g, '"'],
  [/&apos;/g, "'"],
  [/&#39;/g, "'"],
  [/&lt;/g, '<'],
  [/&gt;/g, '>'],
  [/&amp;/g, '&'],
]

export function splitInlineQuestionnaireContent(content, keyPrefix = 'questionnaire') {
  const text = normalizeTransportText(String(content || ''))
  const parts = []
  let lastIndex = 0
  let count = 0

  for (const match of collectInlineProtocolMatches(text)) {
    if (match.start > lastIndex) {
      parts.push({
        type: 'markdown',
        key: `${keyPrefix}-text-${count}`,
        content: text.slice(lastIndex, match.start),
      })
    }

    const tag = match.tag
    const attrs = match.attrs
    const rawPayload = match.rawPayload
    const isResponse = tag.endsWith('-response')
    const isArtifacts = ARTIFACT_TAGS.includes(tag)
    const baseTag = isResponse ? tag.slice(0, -'-response'.length) : tag
    const payload = isArtifacts
      ? parseArtifacts(rawPayload, { tag })
      : isResponse
        ? parseQuestionnaireResponse(rawPayload, baseTag)
        : parseQuestionnaire(rawPayload, {
            attrs,
            tag: baseTag,
            id: `${keyPrefix}_q${count + 1}`,
            format: match.format,
            hasPreface: match.hasPreface,
          })

    if (payload) {
      parts.push({
        type: isArtifacts ? 'artifacts' : isResponse ? 'questionnaire_response' : 'questionnaire',
        key: `${keyPrefix}-${isArtifacts ? 'artifacts' : isResponse ? 'response' : 'questionnaire'}-${count}`,
        tag: baseTag,
        payload,
        rawText: match.rawText,
      })
    } else {
      parts.push({
        type: 'markdown',
        key: `${keyPrefix}-invalid-${count}`,
        content: match.rawText,
      })
    }

    count += 1
    lastIndex = match.end
  }

  if (lastIndex < text.length) {
    parts.push({
      type: 'markdown',
      key: `${keyPrefix}-text-${count}`,
      content: text.slice(lastIndex),
    })
  }

  return parts
}

function collectInlineProtocolMatches(text) {
  const { matches, codeRanges } = collectFencedQuestionnaireMatches(text)
  let match

  TAG_PATTERN.lastIndex = 0
  while ((match = TAG_PATTERN.exec(text)) !== null) {
    if (isInsideRange(match.index, codeRanges)) continue
    matches.push({
      start: match.index,
      end: TAG_PATTERN.lastIndex,
      tag: match[1].toLowerCase(),
      attrs: parseAttributes(match[2] || ''),
      rawPayload: match[3] || '',
      rawText: match[0],
      format: 'json',
    })
  }

  matches.sort((left, right) => left.start - right.start || right.end - left.end)
  const nonOverlapping = []
  let lastEnd = -1
  for (const candidate of matches) {
    if (candidate.start < lastEnd) continue
    nonOverlapping.push(candidate)
    lastEnd = candidate.end
  }
  return nonOverlapping
}

function collectFencedQuestionnaireMatches(text) {
  const matches = []
  const codeRanges = []
  const lines = lineEntries(text)

  for (let index = 0; index < lines.length; index += 1) {
    const opening = markdownFenceOpening(lines[index].body)
    if (!opening) continue

    const tag = opening.info.toLowerCase()
    const isQuestionnaire = opening.marker === '`' && QUESTIONNAIRE_TAGS.includes(tag)
    let closingIndex = -1
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      if (isMarkdownFenceClosing(lines[cursor].body, opening)) {
        closingIndex = cursor
        break
      }
    }

    if (!isQuestionnaire || closingIndex < 0) {
      const rangeEnd = closingIndex >= 0 ? lines[closingIndex].end : text.length
      codeRanges.push([lines[index].start, rangeEnd])
      if (closingIndex >= 0) index = closingIndex
      else break
      continue
    }

    const payloadStart = lines[index].end
    const end = lines[closingIndex].contentEnd
    matches.push({
      start: lines[index].start,
      end,
      tag,
      attrs: {},
      rawPayload: text.slice(payloadStart, lines[closingIndex].start),
      rawText: text.slice(lines[index].start, end),
      format: 'yaml',
    })
    index = closingIndex
  }

  codeRanges.push(...collectIndentedCodeRanges(
    lines,
    [...codeRanges, ...matches.map((match) => [match.start, match.end])]
  ))
  codeRanges.push(...collectInlineCodeRanges(
    text,
    [
      ...codeRanges,
      ...matches.map((match) => [match.start, match.end]),
    ]
  ))
  codeRanges.sort((left, right) => left[0] - right[0])

  if (matches.length > 0) {
    matches[0].hasPreface = hasVisibleQuestionnairePreface(
      text.slice(0, matches[0].start),
      codeRanges
    )
  }

  return { matches, codeRanges }
}

function collectIndentedCodeRanges(lines, excludedRanges) {
  return lines
    .filter((line) => (
      /^(?: {4}|\t)/.test(line.body)
      && !isInsideRange(line.start, excludedRanges)
    ))
    .map((line) => [line.start, line.end])
}

function collectInlineCodeRanges(text, blockRanges) {
  const ranges = []
  const sortedBlocks = [...blockRanges].sort((left, right) => left[0] - right[0])
  let segmentStart = 0
  for (const [blockStart, blockEnd] of [...sortedBlocks, [text.length, text.length]]) {
    ranges.push(...collectInlineCodeRangesInSegment(text, segmentStart, blockStart))
    segmentStart = Math.max(segmentStart, blockEnd)
  }
  return ranges
}

function collectInlineCodeRangesInSegment(text, segmentStart, segmentEnd) {
  const ranges = []
  let cursor = segmentStart
  while (cursor < segmentEnd) {
    if (text[cursor] !== '`') {
      cursor += 1
      continue
    }

    let openerEnd = cursor + 1
    while (text[openerEnd] === '`') openerEnd += 1
    const delimiter = '`'.repeat(openerEnd - cursor)
    let closing = text.indexOf(delimiter, openerEnd)
    while (closing >= 0 && closing < segmentEnd) {
      const beforeIsTick = closing > 0 && text[closing - 1] === '`'
      const afterIsTick = text[closing + delimiter.length] === '`'
      if (!beforeIsTick && !afterIsTick) break
      closing = text.indexOf(delimiter, closing + delimiter.length)
    }
    if (closing < 0 || closing >= segmentEnd) {
      cursor = openerEnd
      continue
    }
    ranges.push([cursor, closing + delimiter.length])
    cursor = closing + delimiter.length
  }
  return ranges
}

export function canSubmitQuestionnaireMessage(messages, messageIndex, readonly = false) {
  if (readonly) return false
  if (!Array.isArray(messages) || messageIndex < 0 || messageIndex >= messages.length) {
    return false
  }

  for (let index = messageIndex + 1; index < messages.length; index += 1) {
    const message = messages[index]
    if (message?.role === 'user') return false
    if (message?.role !== 'assistant') continue
    const messageType = message.message_type || message.type
    if (messageType === 'empty' || messageType === 'token_usage') continue
    return false
  }
  return true
}

function hasVisibleQuestionnairePreface(prefix, codeRanges) {
  let visible = ''
  let cursor = 0
  for (const [start, end] of codeRanges) {
    if (start >= prefix.length) break
    visible += prefix.slice(cursor, Math.max(cursor, start))
    cursor = Math.max(cursor, Math.min(end, prefix.length))
  }
  visible += prefix.slice(cursor)
  return visible.replace(TAG_PATTERN, '').trim().length > 0
}

function lineEntries(text) {
  const lines = []
  let start = 0
  while (start < text.length) {
    const newline = text.indexOf('\n', start)
    const end = newline < 0 ? text.length : newline + 1
    const contentEnd = newline < 0 ? text.length : newline
    lines.push({
      start,
      end,
      contentEnd,
      body: text.slice(start, contentEnd).replace(/\r$/, ''),
    })
    start = end
  }
  return lines
}

function markdownFenceOpening(line) {
  const match = line.match(/^[ \t]{0,3}(`{3,}|~{3,})(.*)$/)
  if (!match) return null
  const marker = match[1][0]
  const info = match[2].trim()
  if (marker === '`' && info.includes('`')) return null
  return { marker, length: match[1].length, info }
}

function isMarkdownFenceClosing(line, opening) {
  const escaped = opening.marker === '`' ? '`' : '~'
  return new RegExp(`^[ \\t]{0,3}${escaped}{${opening.length},}[ \\t]*$`).test(line)
}

function isInsideRange(index, ranges) {
  return ranges.some(([start, end]) => start <= index && index < end)
}

export function parseArtifacts(rawJson, { tag = 'artifacts' } = {}) {
  const decoded = decodeJsonObject(rawJson)
  if (!decoded || !Array.isArray(decoded.items)) return null

  const items = decoded.items
    .map((item, index) => normalizeArtifactItem(item, index))
    .filter(Boolean)

  if (items.length === 0) return null

  return {
    tag,
    title: asString(decoded.title).trim(),
    items,
  }
}

export function parseQuestionnaire(
  rawPayload,
  {
    attrs = {},
    tag = 'questionnaire',
    id = 'questionnaire_q1',
    format = 'json',
    hasPreface = true,
  } = {}
) {
  const decoded = format === 'yaml'
    ? decodeYamlObject(rawPayload)
    : decodeJsonObject(rawPayload)
  if (format === 'yaml' && (!hasPreface || !isStrictFencedQuestionnaire(decoded, rawPayload))) return null
  if (!decoded || !Array.isArray(decoded.questions)) return null

  const questions = decoded.questions
    .map((rawQuestion, index) => normalizeQuestion(rawQuestion, index))
    .filter(Boolean)

  if (questions.length === 0) return null

  const attrTimeout = parsePositiveInt(attrs.timeout_seconds)
  const payloadTimeout = parsePositiveInt(decoded.timeout_seconds)

  return {
    id,
    tag,
    title: asString(decoded.title).trim(),
    uiText: normalizeQuestionnaireUiText(decoded.ui_text),
    timeoutSeconds: attrTimeout || payloadTimeout || 0,
    questions,
  }
}

function isStrictFencedQuestionnaire(payload, rawPayload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false
  const payloadText = String(rawPayload || '').trim()
  if (!payloadText || payloadText.startsWith('{') || payloadText.startsWith('[')) return false
  if (/^[ \t]{0,3}(?:`{3,}|~{3,})/m.test(String(rawPayload || ''))) return false
  if (!hasExactFields(payload, ['title', 'questions'])) return false
  if (typeof payload.title !== 'string' || !payload.title.trim()) return false
  if (!Array.isArray(payload.questions) || payload.questions.length === 0) return false

  return payload.questions.every((question) => {
    if (!question || typeof question !== 'object' || Array.isArray(question)) return false
    const type = question.type
    if (!['single_choice', 'multi_choice', 'free_text'].includes(type)) return false
    const allowedFields = type === 'free_text'
      ? ['type', 'text', 'default']
      : ['type', 'text', 'default', 'options', 'allow_other']
    if (!hasOnlyFields(question, allowedFields)) return false
    if (typeof question.text !== 'string' || !question.text.trim()) return false
    if (!Object.prototype.hasOwnProperty.call(question, 'default')) return false

    if (type === 'free_text') return typeof question.default === 'string'
    if (!Array.isArray(question.options) || question.options.length === 0) return false
    if (question.options.some((option) => typeof option !== 'string' || !option.trim())) return false
    if (question.allow_other !== undefined && typeof question.allow_other !== 'boolean') return false
    if (type === 'single_choice') {
      return typeof question.default === 'string' && question.options.includes(question.default)
    }
    return Array.isArray(question.default)
      && question.default.every((value) => typeof value === 'string' && question.options.includes(value))
  })
}

function hasExactFields(value, expected) {
  const keys = Object.keys(value)
  return keys.length === expected.length && expected.every((field) => keys.includes(field))
}

function hasOnlyFields(value, allowed) {
  return Object.keys(value).every((field) => allowed.includes(field))
}

export function buildQuestionnaireSubmission(
  questionnaire,
  draftAnswers,
  status = 'submitted',
  uiText = questionnaire?.uiText
) {
  const resolvedUiText = resolveQuestionnaireUiText(uiText)
  const answers = questionnaire.questions.map((question) => {
    const draft = draftAnswers?.[question.id]
    if (question.type === 'free_text') {
      return {
        question_id: question.id,
        question: question.text,
        type: 'free_text',
        answer: asString(draft).trim(),
      }
    }

    if (question.type === 'multi_choice') {
      const values = Array.isArray(draft?.values) ? draft.values : []
      const labels = values
        .map((value) => labelForValue(question, value, resolvedUiText))
        .filter(Boolean)
      const answer = {
        question_id: question.id,
        question: question.text,
        type: 'multi_choice',
        answer: values,
        values,
        labels,
      }
      if (asString(draft?.otherText).trim()) answer.other_text = asString(draft.otherText).trim()
      return answer
    }

    const value = asString(draft?.value).trim()
    const answer = {
      question_id: question.id,
      question: question.text,
      type: 'single_choice',
      answer: value,
      value,
      label: labelForValue(question, value, resolvedUiText),
    }
    if (asString(draft?.otherText).trim()) answer.other_text = asString(draft.otherText).trim()
    return answer
  })

  const responseTag = `${questionnaire.tag}-response`
  const payload = {
    type: `${questionnaire.tag.replace(/-/g, '_')}_response`,
    questionnaire_id: questionnaire.id,
    status,
    answers,
  }

  return {
    agentText: `<${responseTag}>${JSON.stringify(payload)}</${responseTag}>`,
    displayText: displayTextForAnswers(answers, resolvedUiText),
    answers,
  }
}

export function parseQuestionnaireResponse(rawJson, tag = 'questionnaire') {
  const decoded = decodeJsonObject(rawJson)
  if (!decoded || !Array.isArray(decoded.answers)) return null
  return {
    tag,
    questionnaireId: asString(decoded.questionnaire_id).trim(),
    status: asString(decoded.status).trim() || 'submitted',
    answers: decoded.answers.map(normalizeAnswer).filter(Boolean),
  }
}

export function questionnaireFromAsyncToolResult(
  toolResult,
  { id = 'questionnaire_async_q1' } = {}
) {
  const result = toolResult?.content ?? toolResult
  if (!result || typeof result !== 'object' || Array.isArray(result)) return null
  if (result.success !== true || result.validation_passed !== true) return null
  if (!Array.isArray(result.questions) || result.questions.length === 0) return null
  return parseQuestionnaire(JSON.stringify({
    title: result.title || '',
    questions: result.questions,
  }), { tag: 'questionnaire', id })
}

export function displayTextForAnswers(answers, uiText) {
  const resolvedUiText = resolveQuestionnaireUiText(uiText)
  const lines = [resolvedUiText.answerTitle]
  for (const answer of answers || []) {
    lines.push(
      `${answer.question || answer.question_id || resolvedUiText.questionFallback}`
      + `${resolvedUiText.answerSeparator}${displayValueForAnswer(answer, resolvedUiText)}`
    )
  }
  return lines.join('\n')
}

export function displayValueForAnswer(answer, uiText) {
  const resolvedUiText = resolveQuestionnaireUiText(uiText)
  if (!answer) return resolvedUiText.unanswered
  if (answer.type === 'free_text') {
    const text = asString(answer.answer || answer.text).trim()
    return text || resolvedUiText.unanswered
  }

  const parts = []
  const labels = Array.isArray(answer.labels) && answer.labels.length
    ? answer.labels
    : Array.isArray(answer.answer)
      ? answer.answer
      : [answer.label || answer.answer || answer.value]

  for (const item of labels) {
    const value = asString(item).trim()
    if (value) parts.push(value)
  }
  const otherText = asString(answer.other_text || answer.otherText).trim()
  if (otherText) parts.push(otherText)
  return parts.length
    ? parts.join(resolvedUiText.listSeparator)
    : resolvedUiText.unselected
}

export function initialQuestionnaireDraft(questionnaire) {
  const draft = {}
  for (const question of questionnaire.questions || []) {
    if (question.type === 'free_text') {
      draft[question.id] = question.defaultText || ''
    } else if (question.type === 'multi_choice') {
      draft[question.id] = {
        values: [...question.defaultValues],
        otherText: '',
      }
    } else {
      draft[question.id] = {
        value: question.defaultValue || '',
        otherText: '',
      }
    }
  }
  return draft
}

function normalizeQuestion(rawQuestion, index) {
  if (!rawQuestion || typeof rawQuestion !== 'object') return null
  const type = normalizeQuestionType(rawQuestion.type)
  const text = asString(rawQuestion.text).trim()
  if (!type || !text) return null

  const id = asString(rawQuestion.id).trim() || `q${index + 1}`
  const options = Array.isArray(rawQuestion.options)
    ? rawQuestion.options.map(normalizeOption).filter(Boolean)
    : []

  if (type !== 'free_text' && options.length === 0) return null

  const defaultRaw = rawQuestion.default ?? rawQuestion.default_value
  const defaultValues = Array.isArray(defaultRaw)
    ? defaultRaw.map((value) => asString(value).trim()).filter(Boolean)
    : []
  const defaultValue = !Array.isArray(defaultRaw) ? asString(defaultRaw).trim() : ''

  return {
    id,
    type,
    text,
    options,
    allowOther: rawQuestion.allow_other === true,
    defaultValue,
    defaultValues,
    defaultText: type === 'free_text' ? defaultValue || asString(rawQuestion.default_text).trim() : '',
  }
}

function normalizeQuestionType(type) {
  const value = asString(type).trim()
  if (value === 'single_choice') return 'single_choice'
  if (value === 'multi_choice' || value === 'multiple_choice') return 'multi_choice'
  if (value === 'free_text' || value === 'text') return 'free_text'
  return null
}

function normalizeOption(rawOption) {
  if (typeof rawOption === 'string') {
    const value = rawOption.trim()
    return value ? { value, label: value } : null
  }
  if (!rawOption || typeof rawOption !== 'object') return null
  const value = asString(rawOption.value).trim() || asString(rawOption.label).trim()
  const label = asString(rawOption.label).trim() || value
  return value && label ? { value, label } : null
}

function normalizeArtifactItem(rawItem, index) {
  if (!rawItem || typeof rawItem !== 'object') return null
  const path = asString(rawItem.path).trim()
  if (!path) return null
  return {
    id: asString(rawItem.id).trim() || `artifact_${index + 1}`,
    type: asString(rawItem.type).trim() || inferArtifactType(path),
    title: asString(rawItem.title).trim() || fileNameFromPath(path),
    path,
    status: asString(rawItem.status).trim(),
  }
}

function inferArtifactType(path) {
  const extension = path.split('.').pop()?.toLowerCase() || ''
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(extension)) return 'image'
  if (['mp4', 'mov', 'webm'].includes(extension)) return 'video'
  if (['csv', 'xlsx', 'xls'].includes(extension)) return 'spreadsheet'
  if (['ppt', 'pptx'].includes(extension)) return 'presentation'
  if (extension === 'pdf') return 'pdf'
  if (['md', 'markdown'].includes(extension)) return 'markdown'
  return 'file'
}

function fileNameFromPath(path) {
  return path.split('/').filter(Boolean).pop() || path
}

function normalizeAnswer(rawAnswer) {
  if (!rawAnswer || typeof rawAnswer !== 'object') return null
  const type = normalizeQuestionType(rawAnswer.type)
  const question = asString(rawAnswer.question).trim()
  if (!type || !question) return null
  return {
    ...rawAnswer,
    type,
    question,
  }
}

function decodeJsonObject(rawJson) {
  for (const candidate of jsonDecodeCandidates(rawJson)) {
    try {
      const decoded = JSON.parse(candidate)
      if (decoded && typeof decoded === 'object' && !Array.isArray(decoded)) {
        return decoded
      }
      if (typeof decoded === 'string') {
        const nestedDecoded = JSON.parse(decoded)
        if (nestedDecoded && typeof nestedDecoded === 'object' && !Array.isArray(nestedDecoded)) {
          return nestedDecoded
        }
      }
    } catch {
      // Try the next normalization candidate.
    }
  }
  return null
}

function decodeYamlObject(rawYaml) {
  try {
    const decoded = loadYaml(String(rawYaml || ''))
    return decoded && typeof decoded === 'object' && !Array.isArray(decoded)
      ? decoded
      : null
  } catch {
    return null
  }
}

function jsonDecodeCandidates(rawJson) {
  const normalized = String(rawJson || '').trim()
  if (!normalized) return []
  const htmlDecoded = decodeBasicHtmlEntities(normalized)
  const unescaped = unescapeTransportJson(normalized)
  const htmlDecodedUnescaped = unescapeTransportJson(htmlDecoded)
  return [...new Set([
    normalized,
    unescaped,
    htmlDecoded,
    htmlDecodedUnescaped,
    normalizeSmartJsonQuotes(normalized),
    normalizeSmartJsonQuotes(unescaped),
    normalizeSmartJsonQuotes(htmlDecoded),
    normalizeSmartJsonQuotes(htmlDecodedUnescaped),
  ])]
}

function normalizeTransportText(value) {
  const trimmed = String(value || '')
  if (!trimmed.startsWith('"') || !trimmed.endsWith('"')) {
    return decodeBasicHtmlEntities(trimmed)
  }
  try {
    const decoded = JSON.parse(trimmed)
    return typeof decoded === 'string' ? decodeBasicHtmlEntities(decoded) : decodeBasicHtmlEntities(trimmed)
  } catch {
    return decodeBasicHtmlEntities(trimmed)
  }
}

function unescapeTransportJson(value) {
  return value
    .replace(/\\"/g, '"')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t')
    .replace(/<\\\//g, '</')
}

function decodeBasicHtmlEntities(value) {
  return BASIC_HTML_ENTITIES.reduce((text, [pattern, replacement]) => (
    text.replace(pattern, replacement)
  ), value)
}

function normalizeSmartJsonQuotes(value) {
  return value
    .replace(/\u201c/g, '"')
    .replace(/\u201d/g, '"')
    .replace(/\u2018/g, "'")
    .replace(/\u2019/g, "'")
}

function parseAttributes(rawAttrs) {
  const attrs = {}
  const pattern = /([a-zA-Z_:-][a-zA-Z0-9_:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/g
  let match
  while ((match = pattern.exec(rawAttrs || '')) !== null) {
    attrs[match[1]] = match[2] ?? match[3] ?? match[4] ?? ''
  }
  return attrs
}

function parsePositiveInt(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

function labelForValue(question, value, uiText) {
  const stringValue = asString(value).trim()
  if (!stringValue) return ''
  if (stringValue === '__questionnaire_other__') return uiText.other
  return question.options.find((option) => option.value === stringValue)?.label || stringValue
}

function normalizeQuestionnaireUiText(rawUiText) {
  if (!rawUiText || typeof rawUiText !== 'object') return {}
  return {
    other: asString(rawUiText.other).trim(),
    answerTitle: asString(rawUiText.answer_title ?? rawUiText.answerTitle).trim(),
    questionFallback: asString(
      rawUiText.question_fallback ?? rawUiText.questionFallback
    ).trim(),
    unanswered: asString(rawUiText.unanswered).trim(),
    unselected: asString(rawUiText.unselected).trim(),
    answerSeparator: asString(
      rawUiText.answer_separator ?? rawUiText.answerSeparator
    ),
    listSeparator: asString(
      rawUiText.list_separator ?? rawUiText.listSeparator
    ),
  }
}

function resolveQuestionnaireUiText(rawUiText) {
  const normalized = normalizeQuestionnaireUiText(rawUiText)
  return Object.fromEntries(
    Object.entries(DEFAULT_UI_TEXT).map(([key, fallback]) => [
      key,
      normalized[key] || fallback,
    ])
  )
}

function asString(value) {
  return typeof value === 'string' ? value : ''
}
