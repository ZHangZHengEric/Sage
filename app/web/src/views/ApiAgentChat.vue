<template>
  <div class="api-doc">
    <div class="doc-header">
      <div class="doc-header-left">
        <h2>Agent对话 · API参考</h2>
      </div>

    </div>

    <div class="endpoint-bar">
      <span class="method-badge">POST</span>
      <span class="endpoint-path">{{ endpoint }}/api/stream</span>
    </div>

    <div class="doc-content">
      

      <section class="doc-section">
        <div class="section-title">Headers</div>
        <div class="section-block">
          <div class="chip-group">
            <span class="chip">Content-Type</span>
            <span class="chip">application/json</span>
            <span class="chip danger">required</span>
          </div>
        </div>
      </section>

      <section class="doc-section">
        <div class="section-title">Body <span class="muted">application/json</span></div>
        <div class="doc-hint danger">不同会话请使用不同的 <code>session_id</code>。<code>system_context</code> 按业务值填写。</div>
        <div class="param-list">
          <div class="param-item" v-for="p in params" :key="p.name">
            <div class="param-head">
              <div class="param-name">{{ p.name }}</div>
              <div class="param-tags">
                <span class="chip type">{{ p.type }}</span>
                <span v-if="p.required" class="chip danger">必填</span>
              </div>
            </div>
            <div class="param-desc">{{ p.desc }}</div>
            <div v-if="p.children && p.children.length" class="param-children">
              <div class="param-child" v-for="c in p.children" :key="p.name + '-' + c.name">
                <div class="param-head">
                  <div class="param-name">{{ c.name }}</div>
                  <div class="param-tags">
                    <span class="chip type">{{ c.type }}</span>
                    <span v-if="c.required" class="chip danger">必填</span>
                  </div>
                </div>
                <div class="param-desc">{{ c.desc }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="doc-section">
          <div class="section-title">请求示例</div>
          <a href="#" class="link" @click.prevent="goToAgentList">前往Agent列表查看调用示例</a>
        </div>
      </section>

      <section class="doc-section">
        <div class="section-title">Response <span class="muted">200 · application/json</span></div>
        <div class="param-list">
          <div class="param-item" v-for="p in responseParams" :key="p.name">
            <div class="param-head">
              <div class="param-name">{{ p.name }}</div>
              <div class="param-tags">
                <span class="chip type">{{ p.type }}</span>
                <span v-if="p.required" class="chip danger">必填</span>
              </div>
            </div>
            <div class="param-desc">{{ p.desc }}</div>
            <div v-if="p.children && p.children.length" class="param-children">
              <div class="param-child" v-for="c in p.children" :key="p.name + '-' + c.name">
                <div class="param-head">
                  <div class="param-name">{{ c.name }}</div>
                  <div class="param-tags">
                    <span class="chip type">{{ c.type }}</span>
                    <span v-if="c.required" class="chip danger">必填</span>
                  </div>
                </div>
                <div class="param-desc">{{ c.desc }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="section-title">分块事件说明</div>
        <div class="param-list">
          <div class="param-item" v-for="p in chunkParams" :key="p.name">
            <div class="param-head">
              <div class="param-name">{{ p.name }}</div>
              <div class="param-tags">
                <span class="chip type">{{ p.type }}</span>
              </div>
            </div>
            <div class="param-desc">{{ p.desc }}</div>
            <div v-if="p.children && p.children.length" class="param-children">
              <div class="param-child" v-for="c in p.children" :key="p.name + '-' + c.name">
                <div class="param-head">
                  <div class="param-name">{{ c.name }}</div>
                  <div class="param-tags">
                    <span class="chip type">{{ c.type }}</span>
                  </div>
                </div>
                <div class="param-desc">{{ c.desc }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="code-card">
          <div class="code-card-header">
            <div class="code-card-title">流式响应示例</div>
            <div class="code-card-actions">
              <button class="icon-btn" title="复制" @click="copy(exampleStreamResponse)"><Copy :size="16" /></button>
              <button class="icon-btn" :title="showResponseExample ? '收起' : '展开'" @click="showResponseExample = !showResponseExample">
                <component :is="showResponseExample ? 'ChevronUp' : 'ChevronDown'" :size="16" />
              </button>
            </div>
          </div>
          <div v-show="showResponseExample" class="code-card-body">
            <pre class="code"><code>{{ exampleStreamResponse }}</code></pre>
          </div>
        </div>
      </section>

      <section class="doc-section">
        <div class="section-title">消息类型 type 含义</div>
        <div class="simple-table">
          <div class="simple-head">
            <div>类型</div>
            <div>含义</div>
          </div>
          <div class="simple-row" v-for="t in typeList" :key="t.key">
            <div class="cell name">{{ t.key }}</div>
            <div class="cell desc">{{ t.label }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
  </template>

<script setup>
import { computed, ref } from 'vue'
import { Copy, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { messageTypeLabels } from '../utils/messageLabels.js'
import { useRouter } from 'vue-router'

const endpoint = (
  import.meta.env.VITE_SAGE_API_BASE_URL ||
  import.meta.env.VITE_BACKEND_ENDPOINT ||
  ''
).replace(/\/+$/, '')

const params = [
  { name: 'messages', type: 'Array<Object>', required: true, desc: '历史消息数组，至少包含一条用户消息', children: [
    { name: 'role', type: 'string', required: true, desc: '用户消息填写为 "user"' },
    { name: 'content', type: 'string', required: true, desc: '消息文本内容' },
    { name: 'message_type', type: 'string', required: false, desc: '可选类型标识' }
  ] },
  { name: 'session_id', type: 'string', required: true, desc: '会话唯一标识，需为不同对话设置不同值' },
  { name: 'deep_thinking', type: 'boolean', required: false, desc: '是否启用深度思考，不传表示由服务端自动决定' },
  { name: 'multi_agent', type: 'boolean', required: false, desc: '是否启用多智能体协作，不传表示由服务端自动决定' },
  { name: 'max_loop_count', type: 'number', required: false, desc: '最大循环次数，控制思考或协作迭代上限' },
  { name: 'system_prefix', type: 'string', required: false, desc: '系统提示前缀，用于设定助手的行为或语气' },
  { name: 'system_context', type: 'object', required: false, desc: '系统上下文信息，根据真实业务值填写' },
  { name: 'available_workflows', type: 'object', required: false, desc: '可用工作流定义，用于扩展处理流程' },
  { name: 'llm_model_config', type: 'object', required: false, desc: '模型配置', children: [
    { name: 'model', type: 'string', required: false, desc: '模型名称' },
    { name: 'max_tokens', type: 'number', required: false, desc: '最大生成长度' },
    { name: 'temperature', type: 'number', required: false, desc: '采样温度' }
  ] },
  { name: 'available_tools', type: 'Array<Object>', required: false, desc: '可用工具列表', children: [
    { name: 'name', type: 'string', required: true, desc: '工具名称' },
    { name: 'description', type: 'string', required: false, desc: '工具描述' },
    { name: 'parameters', type: 'object', required: false, desc: '参数字典，按工具定义为准' }
  ] }
]

const exampleBody = {
  messages: [ { role: 'user', content: '你好，请帮我处理一个任务' } ],
  session_id: 'demo-session',
  deep_thinking: null,
  multi_agent: null,
  max_loop_count: 20,
  system_prefix: '',
  system_context: {},
  available_workflows: {},
  llm_model_config: null,
  available_tools: []
}

const responseParams = [
  { name: 'type', type: 'enum', required: true, desc: '消息类型，如 do_subtask_result、token_usage、stream_end ，具体枚举类型请参考消息类型 type 含义' },
  { name: 'message_type', type: 'string', required: false, desc: '消息类型，通常与 type 相同. 兼容字段' },
  { name: 'role', type: '"user" | "assistant" | "tool"', required: false, desc: '角色标识，流式事件如 stream_end 不携带' },
  { name: 'message_id', type: 'string', required: false, desc: '消息唯一ID' },
  { name: 'timestamp', type: 'number', required: true, desc: '时间戳（秒）' },
  { name: 'chunk_id', type: 'string', required: false, desc: '流式分片ID' },
  { name: 'is_final', type: 'boolean', required: false, desc: '是否最终消息' },
  { name: 'session_id', type: 'string', required: false, desc: '会话ID' },
  { name: 'content', type: 'string', required: false, desc: '原始内容，可能为空' },
  { name: 'show_content', type: 'string', required: false, desc: '展示内容，优先用于渲染' },
  { name: 'tool_calls', type: 'Array<Object>', required: false, desc: '工具调用列表' },
  { name: 'tool_call_id', type: 'string', required: false, desc: '工具调用结果关联ID，仅 role=tool 时存在' },
  { name: 'metadata', type: 'object', required: false, desc: '附加信息', children: [
    { name: 'token_usage', type: 'object', required: false, desc: '令牌用量统计，包含 total_info 与 per_step_info' },
    { name: 'session_id', type: 'string', required: false, desc: '会话ID（部分实现中放入metadata）' }
  ] },
  { name: 'total_stream_count', type: 'number', required: false, desc: '当 type=stream_end 时返回总流事件数' }
]

const chunkParams = [
  { name: 'chunk_start', type: 'event', desc: '开始分块，返回本次分块的 chunk_id；后续所有 json_chunk 与 chunk_end 的 chunk_id 与之保持一致', children: [
    { name: 'chunk_id', type: 'string', required: true, desc: '分块唯一标识' },
    { name: 'is_chunk', type: 'boolean', required: true, desc: '为 true，表示当前为分块事件' }
  ] },
  { name: 'json_chunk', type: 'event', desc: '分块内容，可能为流式片段或结构化片段；在 UI 侧累积并拼接', children: [
    { name: 'chunk_id', type: 'string', required: true, desc: '与 chunk_start 的 chunk_id 相同' },
    { name: 'content', type: 'string | object', required: false, desc: '片段内容，可能为空字符串或结构化对象' },
    { name: 'is_chunk', type: 'boolean', required: true, desc: '为 true' }
  ] },
  { name: 'chunk_end', type: 'event', desc: '结束分块，表示该 chunk 已完成；前端可关闭累积并触发最终渲染', children: [
    { name: 'chunk_id', type: 'string', required: true, desc: '与 chunk_start 的 chunk_id 相同' },
    { name: 'is_chunk', type: 'boolean', required: true, desc: '为 true' }
  ] }
]

const typeList = computed(() => Array.from(messageTypeLabels.entries()).map(([key, label]) => ({ key, label })))

const exampleStreamResponse = `{"role": "assistant", "content": "您好", "message_id": "8c89c757-1ce5-4860-9ad5-6d20d6defdef", "show_content": "您好", "type": "do_subtask_result", "message_type": "do_subtask_result", "timestamp": 1764040749.2765763, "chunk_id": "81d993e8-6013-4862-b083-bdaeac8b5f15", "is_final": false, "is_chunk": false, "metadata": {}, "session_id": "demo-session"}
{"role": "assistant", "content": "", "message_id": "98516185-a102-47b8-acfa-b4320f988f54", "type": "token_usage", "message_type": "token_usage", "timestamp": 1764040752.8867667, "chunk_id": "d16899a8-e8bd-40f5-97b1-b1f1ab774806", "is_final": false, "is_chunk": false, "metadata": {"token_usage": {"total_info": {"completion_tokens": 146, "prompt_tokens": 1583, "total_tokens": 1729}, "per_step_info": [{"step_name": "direct_execution", "usage": {"completion_tokens": 123, "prompt_tokens": 1067, "total_tokens": 1190, "completion_tokens_details": null, "prompt_tokens_details": null}}, {"step_name": "task_complete_judge", "usage": {"completion_tokens": 23, "prompt_tokens": 516, "total_tokens": 539, "completion_tokens_details": null, "prompt_tokens_details": null}}]}, "session_id": "demo-session"}, "session_id": "demo-session"}
{"type": "stream_end", "session_id": "demo-session", "timestamp": 1764040752.909369, "total_stream_count": 29}`

const showResponseExample = ref(true)

const router = useRouter()
const goToAgentList = () => {
  router.push({ name: 'AgentConfig' })
}

const copy = async (text) => {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(String(text))
      return
    }
  } catch (_) {}
  const ta = document.createElement('textarea')
  ta.value = String(text)
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  ta.style.top = '0'
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  try {
    document.execCommand('copy')
  } catch (_) {}
  document.body.removeChild(ta)
}

//

const scrollTo = (id) => {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<style scoped>
.api-doc { padding: 24px; max-width: 1000px; margin: 0 auto; }
.doc-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.doc-header-left h2 { margin: 0 0 6px 0; font-size: 22px; font-weight: 700; color: #1f2937; }
.doc-subtitle { margin: 0; color: rgba(0,0,0,0.6); }
.doc-header-right { display: flex; align-items: center; gap: 12px; }
.lang-toggle { display: inline-flex; background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 999px; overflow: hidden; }
.toggle-btn { padding: 6px 12px; border: none; background: transparent; color: #374151; cursor: pointer; }
.toggle-btn.active { background: #ffffff; }
.primary-btn { padding: 6px 12px; border-radius: 8px; border: 1px solid #e5e7eb; background: #4f46e5; color: #ffffff; cursor: pointer; }
.link { color: #4f46e5; font-weight: 600; cursor: pointer; text-decoration: none; }
.link:hover { text-decoration: underline; }

.endpoint-bar { display: flex; align-items: center; gap: 10px; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; background: #ffffff; }
.method-badge { display: inline-block; padding: 4px 8px; border-radius: 6px; background: #eef2ff; color: #4f46e5; font-weight: 700; }
.endpoint-path { color: #111827; font-weight: 600; }
.ghost-btn { margin-left: auto; background: transparent; border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px 10px; color: #374151; cursor: pointer; }

.doc-content { display: block; }

.doc-section { margin-top: 24px; }
.section-title { font-weight: 700; color: #111827; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.muted { color: #6b7280; font-weight: 400; }
.section-block { border: 1px solid #e5e7eb; border-radius: 12px; background: #ffffff; padding: 12px; }
.chip-group { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.chip { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; background: #f3f4f6; color: #374151; border: 1px solid #e5e7eb; }
.chip.danger { background: #fee2e2; color: #ef4444; border-color: #fecaca; }
.field { margin-top: 8px; }
.field label { display: block; color: #6b7280; margin-bottom: 6px; }
.input { width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px 10px; }
.textarea { width: 100%; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px 10px; }

.doc-hint { padding: 10px 12px; border-radius: 8px; margin-bottom: 12px; }
.doc-hint.danger { background: #fff2f0; border: 1px solid #ffccc7; color: #cf1322; }

.param-list { display: grid; gap: 12px; }
.param-item { border-top: 2px solid #e5e7eb;  background: #ffffff; padding: 12px; }
.param-head { display: flex; align-items: center; justify-content: flex-start; gap: 8px; flex-wrap: wrap; }
.param-name { font-weight: 700; color: #1f2937; padding-top: 10px; }
.param-tags { display: inline-flex; gap: 6px; }
.param-tags .chip.type { background: #eef2ff; color: #4f46e5; border-color: #e0e7ff; }
.param-desc { color: #374151; margin-top: 6px; }
.param-children { border-top: 1px solid #f3f4f6; padding-left: 20px; margin-top: 10px; display: grid; gap: 10px; }
.param-child .param-name { font-weight: 600; }

.code-card { border: 1px solid #e5e7eb; border-radius: 12px; background: #ffffff; margin-top: 12px; }
.code-card-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid #e5e7eb; }
.code-card-title { font-weight: 700; color: #1f2937; }
.code-card-actions { display: flex; gap: 6px; }
.icon-btn { background: transparent; color: #374151; border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px; cursor: pointer; }
.icon-btn:hover { background: #f3f4f6; }
.code-card-body { padding: 10px 12px; }
.code { background: #0b1020; color: #e5e7eb; border-radius: 8px; padding: 14px 16px; overflow: auto; }

.sub-table { display: none; }

.inline-actions { padding: 12px; border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; }

.simple-table { border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; border-left: none; border-right: none; background: #ffffff; border-radius: 0; }
.simple-head { display: grid; grid-template-columns: 220px 140px 1fr; gap: 0; background: #f9fafb; padding: 10px 12px; color: #6b7280; font-weight: 600; }
.simple-row { display: grid; grid-template-columns: 220px 140px 1fr; gap: 0; border-top: 1px solid #f3f4f6; padding: 10px 12px; }

.response-preview { display: grid; gap: 10px; grid-template-columns: 1fr; margin-top: 12px; }

@media (max-width: 1024px) {
  .simple-head, .simple-row { grid-template-columns: 160px 120px 1fr; }
}

@media (max-width: 768px) {
  .api-doc { padding: 16px; max-width: 100%; }
  .simple-head, .simple-row { grid-template-columns: 140px 1fr; }
}
</style>
