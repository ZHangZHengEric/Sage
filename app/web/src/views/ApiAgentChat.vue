<template>
  <div class="h-full overflow-y-auto w-full">
    <div class="container mx-auto py-6 max-w-5xl">
      <div class="flex items-center justify-between mb-6">
      <div class="space-y-1">
        <h2 class="text-2xl font-bold tracking-tight">Agent对话 · API参考</h2>
      </div>
    </div>

    <Card class="mb-8">
      <CardContent class="flex items-center gap-4 p-4">
        <Badge variant="secondary" class="font-bold text-primary">POST</Badge>
        <span class="break-all font-mono font-medium">{{ endpoint }}/api/stream</span>
      </CardContent>
    </Card>

    <div class="space-y-8">
      
      <section>
        <h3 class="text-lg font-bold mb-4 flex items-center gap-2">Headers</h3>
        <Card>
          <CardContent class="p-4">
            <div class="flex gap-2 flex-wrap">
              <Badge variant="outline">Content-Type</Badge>
              <Badge variant="secondary">application/json</Badge>
              <Badge variant="destructive">required</Badge>
            </div>
          </CardContent>
        </Card>
      </section>

      <section>
        <h3 class="text-lg font-bold mb-4 flex items-center gap-2">
          Body <span class="text-muted-foreground font-normal text-sm">application/json</span>
        </h3>
        
        <Alert variant="destructive" class="mb-4">
          <AlertTitle>Attention</AlertTitle>
          <AlertDescription>
            不同会话请使用不同的 <code>session_id</code>。<code>system_context</code> 按业务值填写。
          </AlertDescription>
        </Alert>

        <div class="grid gap-4">
          <Card v-for="p in params" :key="p.name">
            <CardHeader class="p-4 pb-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-bold">{{ p.name }}</span>
                <Badge variant="secondary">{{ p.type }}</Badge>
                <Badge v-if="p.required" variant="destructive">必填</Badge>
              </div>
            </CardHeader>
            <CardContent class="p-4 pt-0">
              <p class="text-sm text-muted-foreground">{{ p.desc }}</p>
              
              <div v-if="p.children && p.children.length" class="mt-4 pl-4 border-l-2 border-muted space-y-4">
                <div v-for="c in p.children" :key="p.name + '-' + c.name">
                  <div class="flex items-center gap-2 flex-wrap mb-1">
                    <span class="font-semibold text-sm">{{ c.name }}</span>
                    <Badge variant="secondary" class="text-xs">{{ c.type }}</Badge>
                    <Badge v-if="c.required" variant="destructive" class="text-xs">必填</Badge>
                  </div>
                  <p class="text-xs text-muted-foreground">{{ c.desc }}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div class="mt-8">
          <h3 class="text-lg font-bold mb-4">请求示例</h3>
          <Button variant="link" class="p-0 h-auto text-primary" @click="goToAgentList">
            前往Agent列表查看调用示例
          </Button>
        </div>
      </section>

      <section>
        <h3 class="text-lg font-bold mb-4 flex items-center gap-2">
          Response <span class="text-muted-foreground font-normal text-sm">200 · application/json</span>
        </h3>
        
        <div class="grid gap-4 mb-8">
          <Card v-for="p in responseParams" :key="p.name">
            <CardHeader class="p-4 pb-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-bold">{{ p.name }}</span>
                <Badge variant="secondary">{{ p.type }}</Badge>
                <Badge v-if="p.required" variant="destructive">必填</Badge>
              </div>
            </CardHeader>
            <CardContent class="p-4 pt-0">
              <p class="text-sm text-muted-foreground">{{ p.desc }}</p>
              
              <div v-if="p.children && p.children.length" class="mt-4 pl-4 border-l-2 border-muted space-y-4">
                <div v-for="c in p.children" :key="p.name + '-' + c.name">
                  <div class="flex items-center gap-2 flex-wrap mb-1">
                    <span class="font-semibold text-sm">{{ c.name }}</span>
                    <Badge variant="secondary" class="text-xs">{{ c.type }}</Badge>
                    <Badge v-if="c.required" variant="destructive" class="text-xs">必填</Badge>
                  </div>
                  <p class="text-xs text-muted-foreground">{{ c.desc }}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <h3 class="text-lg font-bold mb-4">分块事件说明</h3>
        <div class="grid gap-4 mb-8">
          <Card v-for="p in chunkParams" :key="p.name">
            <CardHeader class="p-4 pb-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-bold">{{ p.name }}</span>
                <Badge variant="secondary">{{ p.type }}</Badge>
              </div>
            </CardHeader>
            <CardContent class="p-4 pt-0">
              <p class="text-sm text-muted-foreground">{{ p.desc }}</p>
              
              <div v-if="p.children && p.children.length" class="mt-4 pl-4 border-l-2 border-muted space-y-4">
                <div v-for="c in p.children" :key="p.name + '-' + c.name">
                  <div class="flex items-center gap-2 flex-wrap mb-1">
                    <span class="font-semibold text-sm">{{ c.name }}</span>
                    <Badge variant="secondary" class="text-xs">{{ c.type }}</Badge>
                  </div>
                  <p class="text-xs text-muted-foreground">{{ c.desc }}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader class="flex flex-row items-center justify-between p-4">
            <CardTitle class="text-base">流式响应示例</CardTitle>
            <div class="hidden sm:flex gap-2">
              <Button variant="ghost" size="icon" title="复制" @click="copy(exampleStreamResponse)">
                <Copy class="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" :title="showResponseExample ? '收起' : '展开'" @click="showResponseExample = !showResponseExample">
                <component :is="showResponseExample ? 'ChevronUp' : 'ChevronDown'" class="w-4 h-4" />
              </Button>
            </div>
          </CardHeader>
            <CardContent v-show="showResponseExample" class="p-0">
              <pre
                class="bg-slate-950 text-slate-50 p-4 overflow-auto rounded-b-lg text-sm whitespace-pre-wrap break-words">
    <code>{{ exampleStreamResponse }}</code>
  </pre>
            </CardContent>
 
        </Card>
      </section>

      <section>
        <h3 class="text-lg font-bold mb-4">消息类型 type 含义</h3>
        <div class="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead class="w-[200px]">类型</TableHead>
                <TableHead>含义</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="t in typeList" :key="t.key">
                <TableCell class="font-medium">{{ t.key }}</TableCell>
                <TableCell>{{ t.label }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Copy, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { messageTypeLabels } from '../utils/messageLabels.js'
import { useRouter } from 'vue-router'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const endpoint = (
  import.meta.env.VITE_SAGE_API_BASE_URL ||
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


