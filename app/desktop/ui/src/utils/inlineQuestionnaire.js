const QUESTIONNAIRE_TAGS = ['movo-questionnaire', 'ling-questionnaire', 'sage-questionnaire', 'questionnaire']
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
  let match
  let count = 0

  TAG_PATTERN.lastIndex = 0
  while ((match = TAG_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({
        type: 'markdown',
        key: `${keyPrefix}-text-${count}`,
        content: text.slice(lastIndex, match.index),
      })
    }

    const tag = match[1].toLowerCase()
    const attrs = parseAttributes(match[2] || '')
    const rawJson = match[3] || ''
    const isResponse = tag.endsWith('-response')
    const isArtifacts = ARTIFACT_TAGS.includes(tag)
    const baseTag = isResponse ? tag.slice(0, -'-response'.length) : tag
    const payload = isArtifacts
      ? parseArtifacts(rawJson, { tag })
      : isResponse
        ? parseQuestionnaireResponse(rawJson, baseTag)
        : parseQuestionnaire(rawJson, {
            attrs,
            tag: baseTag,
            id: `${keyPrefix}_q${count + 1}`,
          })

    if (payload) {
      parts.push({
        type: isArtifacts ? 'artifacts' : isResponse ? 'questionnaire_response' : 'questionnaire',
        key: `${keyPrefix}-${isArtifacts ? 'artifacts' : isResponse ? 'response' : 'questionnaire'}-${count}`,
        tag: baseTag,
        payload,
      })
    } else {
      parts.push({
        type: 'markdown',
        key: `${keyPrefix}-invalid-${count}`,
        content: match[0],
      })
    }

    count += 1
    lastIndex = TAG_PATTERN.lastIndex
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

export function parseQuestionnaire(rawJson, { attrs = {}, tag = 'questionnaire', id = 'questionnaire_q1' } = {}) {
  const decoded = decodeJsonObject(rawJson)
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
