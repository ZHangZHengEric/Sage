export const protocols = {
  'openai-chat-completions': 'OpenAI Chat Completions',
  'openai-responses': 'OpenAI Responses',
  'anthropic-messages': 'Anthropic Messages',
  'gemini-generate-content': 'Gemini Generate Content',
  orcarouter: 'OrcaRouter',
}
export const modelCapabilities = [
  ['multimodal', '多模态'], ['structured_output', 'JSON / Schema 输出'], ['tool_calling', '工具调用'],
  ['reasoning', '推理'], ['parallel_tool_calls', '并行工具调用'],
]
export const modelProbeNames = { connection: '连接', multimodal: '多模态', structured_output: '严格 Schema 输出', json_object: 'JSON 输出', tool_calling: '工具调用', reasoning_control: '推理控制' }
export function modelCapabilityLabels(item) {
  return modelCapabilities.flatMap(([key, label]) => {
    if (key === 'structured_output') {
      const outcomes = (item.capability_profile?.outcomes || []).filter(outcome => ['structured_output', 'json_object'].includes(outcome.name))
      if (outcomes.length) return outcomes.filter(outcome => outcome.status === 'supported').map(outcome => modelProbeNames[outcome.name])
    }
    return item.capabilities?.[key] ? [label] : []
  })
}
export function providerIdentity(item) {
  let host = ''
  try { host = new URL(item?.base_url).hostname } catch { /* Incomplete addresses stay editable. */ }
  const known = {
    'api.openai.com': ['OpenAI', 'O', 'olive'],
    'api.anthropic.com': ['Anthropic', 'A', 'clay'],
    'generativelanguage.googleapis.com': ['Google Gemini', 'G', 'blue'],
    'api.orcarouter.ai': ['OrcaRouter', 'O', 'ocean'],
  }
  const [name, monogram, tone] = known[host] || [host || '自定义服务', host ? host[0].toUpperCase() : 'C', 'ocean']
  return { name, monogram, tone }
}
export function probeStatus(profile) {
  if (!profile?.outcomes?.length) return { label: '尚未探测', state: 'unverified' }
  if (profile.outcomes.some(item => item.status === 'error')) return { label: '探测需关注', state: 'attention' }
  return { label: '已记录探测', state: 'checked' }
}
export const modelHelp = {
  protocol: '新建配置默认：OpenAI Chat Completions。决定 Sage 与模型服务通信的接口格式。请选择服务商支持的协议；协议不匹配可能导致连接失败或部分能力不可用。',
  base_url: '新建配置默认：https://api.openai.com/v1。切换协议时，未自定义的地址会切换为对应协议的默认地址。使用代理时请填写代理 API 地址；地址需与协议匹配，更改后需要重新探测。',
  model: '服务商 API 接受的模型标识，需与其提供的名称一致。它决定实际调用的模型，以及可用能力、速度和费用。',
  api_key: '用于向此模型服务认证请求。请填写对应服务商的有效密钥；失效或余额不足可能导致请求失败。修改已有配置时，留空会保留已保存的密钥。',
  request_max_output_tokens: '每次请求希望允许的最大输出 Token 数。较小可能截断回答；较大允许更长输出，也可能增加耗时和费用。仍受模型输出上限和服务商限制。',
  context_window: '模型可处理的上下文容量，包含对话、工具内容和输出。请按服务商规格填写；填大不会扩大实际能力。留空时不声明模型容量；若智能体和全局也未设输入预算，上下文管理默认使用 32,768 Token。该预算不代表模型的实际容量。',
  max_output_tokens: '模型自身允许的最大输出 Token 数，与单次请求的输出预算不同，请按服务商规格填写。系统默认：不声明固定上限，不通过此项做本地输出上限校验；服务商的实际限制仍然有效。',
  temperature: '控制生成的随机性。较低通常更稳定，较高通常更丰富但更不确定。系统没有固定默认数值；留空时不发送此参数，由服务商采用该模型的默认值。可用范围及是否支持取决于模型。',
  top_p: '从累计概率达到此阈值的候选中采样。降低通常会收窄措辞选择。系统没有固定默认数值；留空时不发送此参数，由服务商采用该模型的默认值。通常优先调整它或 Temperature 中的一项。',
  reasoning_effort: '向支持的模型请求不同的思考强度。更高可能有助于复杂问题，也可能增加等待和 Token 消耗。系统默认：自动。未探测时不主动指定推理强度；有有效探测结果时按已确认的控制方式执行，可能关闭推理。可用档位取决于模型与接口。',
  multimodal: '系统默认：关闭。声明模型支持图片等非文本输入。开启不会赋予模型原本没有的能力；需与实际模型及接口能力一致。能力探测可能更新此开关。',
  structured_output: '系统默认：关闭。允许模型用于结构化回答。JSON 输出保证返回合法 JSON；严格 Schema 输出由服务端约束指定字段和类型。探测结果分别记录两种能力，仅支持 JSON 时通过提示词描述目标结构，不保证严格符合 Schema。能力探测可能更新此开关。',
  tool_calling: '系统默认：开启。声明模型支持发起工具调用。关闭会影响智能体使用工具的能力；开启前应确认服务商接口支持工具调用。能力探测可能更新此开关。',
  reasoning: '系统默认：关闭。声明模型具备推理能力。实际行为取决于模型、协议和探测结果；开启不会让普通模型变为推理模型。能力探测可能更新此开关。',
  parallel_tool_calls: '系统默认：关闭。声明模型支持在一次回复中发起多个工具调用，有利于独立任务并行处理。不支持的模型可能拒绝相关请求。',
  extra: '系统默认：空对象，不附加扩展参数。用于添加服务商专有参数；不支持的字段或错误的值类型可能导致请求失败。只填写服务商明确支持的参数。',
  probe: '向模型服务发送测试请求，分别检查连接、工具调用、JSON 输出和严格 Schema 输出等能力，可能消耗服务商额度。修改配置后需重新探测；探测结果仅代表本次检查。',
}

// Mirrors protocol defaults and apply_capability_profile in sagents/v2/model/plugins.
// A per-run output budget can override these model-level request defaults.
export function modelFieldHelp(key, model = {}) {
  if (key !== 'request_max_output_tokens') return modelHelp[key]
  const anthropic = model.protocol === 'anthropic-messages'
  const probed = model.capability_profile?.effective_max_output_tokens
  let fallback
  if (Number.isFinite(probed) && probed > 0) {
    const tokens = anthropic ? Math.min(4096, probed) : probed
    fallback = `留空时：根据当前协议和有效探测结果，默认使用 ${tokens.toLocaleString('en-US')} Token。`
  } else {
    fallback = anthropic ? '留空时：当前 Anthropic Messages 协议默认使用 4,096 Token。' : '留空时：当前协议不主动指定输出预算，由服务商采用模型默认值。'
  }
  return `${modelHelp[key]}${fallback}智能体的单次请求预算可覆盖此默认值。`
}
