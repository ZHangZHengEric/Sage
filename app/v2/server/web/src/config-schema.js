export const labels = {
  log_stream: '日志输出位置', log_stdout: '控制台日志', log_root: '日志目录', log_filename: '日志文件名', log_level: '日志级别', log_format: '日志格式',
  log_max_bytes: '日志文件大小上限（字节）', log_backup_count: '保留日志文件数',
  diagnostics_root: '模型诊断目录', diagnostics_storage: '本地诊断存储', diagnostic_content_mode: '诊断内容模式',
  content_mode: '调用链内容模式', sample_rate: '调用链采样比例',
  query_url: '证据查询地址', query_backend: '证据查询后端', query_headers_env: '查询请求头环境变量',
  endpoint: '导出地址', service_name: '服务名', project_name: '项目名', environment: '环境',
  public_key_env: '公钥环境变量', secret_key_env: '私钥环境变量', api_key_env: 'API Key 环境变量',
  max_queue_size: '导出队列上限', max_active_spans: '活动 Span 上限', max_content_chars: '调用链内容字符上限',

  max_inline_characters: '内联字符上限',
  metadata: '包信息', id: 'ID', version: '版本', name: '名称', description: '描述', kind: '类型',
  agents: '智能体', models: '模型路由', credentials: '凭据绑定', runtime: '运行时', policies: '全局策略',
  plugins: '插件', flows: '工作流', entrypoint: '入口', interfaces: '接口', tests: '测试', environments: '环境', files: '资源文件',
  instructions: '系统提示词', inline: '提示词内容', path: '文件路径', mode: '模式', subagents: '子智能体',
  tools: '工具', skills: '技能', budgets: '预算', memory: '记忆', sandbox: '沙箱', network: '网络',
  tool_approval: '工具审批', default: '默认', recall: '自动召回', auto_write: '自动写入', scope: '作用域',
  max_steps: '最大步数', input_tokens: '输入 Token',
  output_tokens: '输出 Token', total_tokens: '总 Token', wall_time_seconds: '运行时间（秒）',
  provider: '协议', plugin: '插件', base_url: 'API 地址', credential: '凭据', model: '模型',
  request: '请求参数', limits: '模型限制', capabilities: '能力', capability_profile: '能力探测档案',
  max_output_tokens: '最大输出 Token', context_window: '上下文窗口', temperature: 'Temperature', top_p: 'Top P', reasoning_effort: '推理强度', extra: '扩展参数',
  multimodal: '多模态', structured_output: 'JSON / Schema 输出', tool_calling: '工具调用', reasoning: '推理', parallel_tool_calls: '并行工具调用',
  type: '类型', loop: '循环', flow: '工作流', config: '配置', preset: '预设', deployment_profile: '部署模式',
  plugin_trust_policy: '插件信任策略', required_guarantees: '运行保障', delegation_model_bindings: '委派模型绑定',
  model_binding: '模型绑定', timeout_seconds: '超时时间（秒）', idle_timeout_seconds: '流空闲超时（秒）',
  max_source_tokens: '摘要输入 Token 上限', summary_target_tokens: '摘要目标 Token', protected_recent_units: '保留近期消息组数',
  max_summary_calls: '单轮摘要调用上限', max_summary_source_tokens: '摘要输入 Token 上限', repeat_threshold: '重复检测阈值',
  max_visible_tools: '最多展示工具数', model_timeout_seconds: '筛选模型超时（秒）', max_concurrent_runs: '运行并发上限',
  max_concurrent_runs_per_tenant: '每用户运行并发上限', max_pending_items: '等待任务上限',
  root: '存储目录', directory: '日志目录', min_level: '日志级别', stream: '输出位置', format: '输出格式',
  table_prefix: '数据库表前缀', encoding_name: '分词编码', max_bytes: '文件大小上限（字节）', backup_count: '保留文件数',
  enabled: '启用', agent: '智能体', scenarios: '场景', gates: '质量门禁', nodes: '节点', edges: '连线', schema_version: 'Schema 版本',
  max_active_characters: '活动技能字符上限',
}
export function resolveSchema(schema = {}, root = {}) {
  if (schema.$ref) return resolveSchema(root.$defs?.[schema.$ref.split('/').at(-1)] || {}, root)
  return schema
}
export function chooseSchema(schema, value, root) {
  schema = resolveSchema(schema, root)
  if (schema.anyOf || schema.oneOf) {
    const options = (schema.anyOf || schema.oneOf).map(item => resolveSchema(item, root)).filter(item => item.type !== 'null')
    return options.find(item => (item.type === 'array' && Array.isArray(value)) || (item.type === 'object' && value && typeof value === 'object' && !Array.isArray(value))) || options[0] || {}
  }
  return schema
}
export function initialValue(schema, root) {
  schema = chooseSchema(schema, undefined, root)
  if (schema.default !== undefined && schema.default !== null) return JSON.parse(JSON.stringify(schema.default))
  if (schema.const !== undefined) return schema.const
  if (schema.enum) return schema.enum[0]
  if (schema.type === 'object' || schema.properties) return Object.fromEntries((schema.required || []).map(key => [key, initialValue(schema.properties?.[key], root)]))
  if (schema.type === 'array') return []
  if (schema.type === 'boolean') return false
  if (schema.type === 'integer' || schema.type === 'number') return schema.minimum ?? (schema.exclusiveMinimum !== undefined ? schema.exclusiveMinimum + 1 : 0)
  return ''
}
