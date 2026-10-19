import { toolState } from './tool-state.js'

export function textOf(message) {
  const content = message?.content
  return typeof content === 'string' ? content : Array.isArray(content)
    ? content.map(part => typeof part === 'string' ? part : part?.text || '').join('') : ''
}
export function toolName(call) { return call?.function?.name || call?.name || 'tool' }
export function parseArguments(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value
  try { const parsed = JSON.parse(value); return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null }
  catch { return null }
}
export function argumentsOf(call) { return call?.function?.arguments ?? call?.arguments ?? '' }
export function pretty(value) {
  if (value === undefined || value === null) return ''
  if (typeof value !== 'string') return JSON.stringify(value, null, 2)
  try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
  return value
}
export function interactionCallId(messages, interaction) {
  if (!interaction || interaction.interaction_type !== 'approval') return ''
  const payload = interaction.payload || {}, calls = messages.flatMap(message => message.toolCalls || [])
  if (payload.tool_call_id) return calls.some(call => call.id === payload.tool_call_id) ? payload.tool_call_id : ''
  const expected = parseArguments(payload.arguments)
  const matches = calls.filter(call => ['awaiting_approval', 'unknown', 'reconciling'].includes(toolState(call)) &&
    toolName(call) === payload.tool_name && (payload.arguments == null || (expected === null ? argumentsOf(call) === payload.arguments : JSON.stringify(canonical(parseArguments(argumentsOf(call)))) === JSON.stringify(canonical(expected)))))
  // Never attach a decision to an arbitrary call when association is ambiguous.
  return matches.length === 1 ? matches[0].id : ''
}
export function transcriptMessages(messages) {
  const calls = new Set(messages.flatMap(message => (message.toolCalls || []).map(call => call.id)))
  const visible = []
  for (const message of messages) {
    if (message.role === 'tool' && calls.has(message.toolCallId)) continue
    if (!textOf(message).trim() && !message.toolCalls?.length) continue
    const last = visible.at(-1)
    if (message.role === 'assistant' && !textOf(message).trim() && last?.role === 'assistant' && !textOf(last).trim()) {
      visible[visible.length - 1] = { ...last, toolCalls: [...(last.toolCalls || []), ...(message.toolCalls || [])] }
    } else visible.push(message)
  }
  return visible
}
export function resultFile(call, result) {
  if (toolState(call, Boolean(result)) !== 'completed') return ''
  const data = parseArguments(textOf(result))
  return data?.status === 'success' && typeof data.file_path === 'string' ? data.file_path : ''
}
export function rememberDescription(payload = {}) {
  const scope = payload.approval_scopes?.includes('session') ? '仅在本会话内记住' : '按服务端允许的范围记住'
  const match = payload.approval_matcher?.summary
  return `${scope}。${match ? `匹配范围：${match}` : '后续匹配到同一工具和相同参数时免重复确认。'}`
}

export function decisionErrorText(error) {
  const text = error?.message || String(error || '')
  const body = text.match(/^HTTP \d+: (\{[\s\S]*\})$/)?.[1]
  if (body) { try { const data = JSON.parse(body); if (typeof data.message === 'string') return data.message } catch { /* Keep the original error when it is not JSON. */ } }
  return text
}
