import { labels } from './config-schema.js'

export function systemCategory(id) {
  if (/^(agent\.|tool\.|model\.|skill\.)/.test(id)) return '模型、工具与智能体'
  if (/^(context\.|memory\.|session-memory\.)/.test(id)) return '记忆与上下文'
  if (/^(execution\.|workspace\.|artifact\.|credentials\.)/.test(id)) return '执行与资源'
  return '运行基础'
}

export const executionNames = { ask: '每次确认', sandboxed: '工作区内自动执行', deny: '禁止命令执行' }
export const policyHelp = {
  overview: '展示此用户保存的执行策略。实际执行仍受服务端与智能体的权限上限限制。此页面只读，不代用户修改策略。',
  shell: '每次确认：命令执行前请求批准。工作区内自动执行：允许在自己的工作区运行代码、修改和删除文件。禁止命令执行：拒绝 Shell。其他工具仍按各自策略审批，网络访问另受服务端与智能体的沙箱策略限制。',
  approval: '暂停表示等待用户处理；直接拒绝表示不进入等待，适合无人值守任务。此设置不会自动扩大用户权限。',
  timeout: '等待审批期间任务暂停；超过有效期，未处理的审批会使任务取消。实际有效期可能受服务端上限进一步限制。',
  saved: '已写入系统默认配置的选择。保存与当前运行不是同一状态；保存的新默认需要重启 Server 才会生效。',
}

const parameterHints = {
  max_visible_tools: '最多向主模型展示的完整工具定义数量。增加有助于覆盖更多工具，也会增加工具定义占用的上下文；直接展示全部工具时不受此限制。',
  root: '此实现使用的根目录。更改目录不会自动迁移原有数据；请确认目录在服务端环境中可用。',
  timeout_seconds: '此实现单次操作的等待时限，以秒计。增加允许等待更久，也会延长发生故障时的等待。',
  model_timeout_seconds: '工具筛选模型请求的等待时限，以秒计。调大允许较慢请求完成，也会延长发生故障时的等待。',
  max_active_characters: '限制同时加载的技能内容字符数。较大可保留更多技能正文，也会增加模型上下文中的内容。',
  model_binding: '选择此能力使用的模型路由。primary 使用主模型，fast 使用辅助模型；更换路由会影响能力的响应速度、费用与判断质量。固定路由不可在此修改。',
  repeat_threshold: '相同操作模式重复达到阈值时请求用户介入。较小会更早中断重复循环，较大允许更多次尝试。',
  max_source_tokens: '限制单次摘要请求处理的原文 Token 数量。较大可覆盖更多历史内容，也可能增加摘要请求的耗时与费用。',
  idle_timeout_seconds: '摘要流连续多久没有收到新内容后判定超时，以秒计。较小能更快发现停滞，也更容易中断较慢的模型。',
  summary_target_tokens: '摘要期望占用的 Token 数量。较大有助于保留细节，同时会占用更多后续对话上下文。',
  protected_recent_units: '压缩历史时保留最近多少组消息不进入摘要。较大有助于保留近期细节，也会减少可以压缩的内容。',
  max_summary_calls: '限制单轮上下文压缩中的摘要调用次数。较小可减少额外调用；达到上限时可能无法继续压缩更多历史。',
  max_summary_source_tokens: '当前压缩实现只保留此字段以读取既有配置，不使用它限制摘要输入。摘要输入上限由摘要器的“摘要输入 Token 上限”控制。',
  endpoint: '追踪数据接收服务的地址。更换后，新产生的追踪数据会发送到此地址；需与所选协议及接收服务配置一致。',
  base_url: 'Langfuse 服务的基础地址。更换后，新产生的追踪数据会发送到新服务，已有数据不会自动迁移。',
  protocol: '追踪数据的传输协议，需与接收端支持的 gRPC 或 HTTP 接口一致；配置不匹配会导致导出失败。',
  insecure: '启用后允许使用不加密的传输连接。关闭时使用安全连接，接收端需配置对应的证书与协议。',
  service_name: '追踪平台中显示的服务名称。用于区分数据来源，不会更改智能体名称或执行行为。',
  environment: '追踪平台中的环境标记，用于区分生产、测试等来源；此标记不会切换实际运行环境。',
  public_key_env: '从服务端哪个环境变量读取 Langfuse 公钥。填写环境变量名，服务端启动时必须能读取该变量。',
  secret_key_env: '从服务端哪个环境变量读取 Langfuse 密钥。填写环境变量名，不在这里填写密钥内容。',
  ingestion_version: '选择 Langfuse 数据接收接口版本，需与部署的服务版本匹配；不会迁移已有追踪数据。',
  content_mode: 'metadata 只记录元信息；redacted 可记录经过脱敏处理的内容。选择会影响追踪平台中可查看的信息范围。',
  max_content_chars: '限制每段记录内容的字符数。较大能保留更多排查信息，也会增加导出数据量。',
  sample_rate: '追踪采样比例，0 表示不采样，1 表示全部采样。降低可减少导出数据量，但部分运行将没有完整追踪。',
  max_queue_size: '最多缓存的待导出追踪事件数。增加可缓冲更多突发事件，同时占用更多内存。',
  max_active_spans: '最多同时保留的活动追踪片段数。增加可覆盖更多并发运行，同时占用更多内存。',
}
const parameterLabels = {
  endpoint: '追踪接收地址', base_url: '服务地址', protocol: '传输协议', insecure: '允许未加密连接',
  service_name: '服务名称', environment: '环境标记', public_key_env: '公钥环境变量', secret_key_env: '密钥环境变量',
  ingestion_version: '接收接口版本', content_mode: '记录内容范围', max_content_chars: '记录内容字符上限',
  sample_rate: '追踪采样比例', max_queue_size: '导出队列上限', max_active_spans: '活动追踪片段上限',
}
export function parameterLabel(key) { return parameterLabels[key] || labels[key] || key }
export function parameterHelp(key, schema = {}) {
  return parameterHints[key] || schema.description || '此参数会随当前实现保存为系统默认配置。服务端未提供更详细的行为说明，请按此实现的定义填写；保存后需重启生效。'
}
