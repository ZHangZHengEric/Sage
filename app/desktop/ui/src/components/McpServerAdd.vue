<template>
  <div class="w-full h-full p-4 overflow-y-auto">
    <div class="max-w-3xl mx-auto">
      <form @submit.prevent="handleSubmit" class="space-y-8 pb-10">
        <div class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Database class="w-5 h-5" />
            {{ t('tools.basicInfo') }}
          </h3>

          <div class="space-y-2">
            <Label for="name">{{ t('tools.serverName') }}</Label>
            <Input
              id="name"
              v-model="form.name"
              type="text"
              :placeholder="t('tools.enterServerName')"
              :readonly="form.kind === 'anytool'"
              required
            />
            <p v-if="form.kind === 'anytool'" class="text-xs text-muted-foreground">
              {{ t('tools.anyToolFixedNameHint') || 'AnyTool is a built-in MCP server and its name cannot be changed.' }}
            </p>
          </div>

          <div class="space-y-2">
            <Label>{{ t('tools.serverMode') || 'Server Mode' }}</Label>
            <Select v-model="form.kind" required>
              <SelectTrigger>
                <SelectValue :placeholder="t('tools.selectServerMode') || 'Select mode'" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="external">{{ t('tools.externalMCP') || 'External MCP' }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div v-if="form.kind === 'external'" class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Code class="w-5 h-5" />
            {{ t('tools.protocolConfig') }}
          </h3>

          <div class="space-y-2">
            <Label>{{ t('tools.protocol') }}</Label>
            <Select v-model="form.protocol" required>
              <SelectTrigger>
                <SelectValue placeholder="Select protocol" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stdio">stdio</SelectItem>
                <SelectItem value="sse">SSE</SelectItem>
                <SelectItem value="streamable_http">Streamable HTTP</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div v-if="form.protocol === 'stdio'" class="space-y-4 animate-in slide-in-from-top-2 duration-200">
            <div class="space-y-2">
              <Label for="command">{{ t('tools.command') }}</Label>
              <Input
                id="command"
                v-model="form.command"
                type="text"
                :placeholder="t('tools.enterCommand')"
                required
              />
            </div>

            <div class="space-y-2">
              <Label for="args">{{ t('tools.arguments') }}</Label>
              <Input
                id="args"
                v-model="form.args"
                type="text"
                :placeholder="t('tools.enterArguments')"
              />
            </div>
          </div>

          <div v-if="form.protocol === 'sse'" class="space-y-2 animate-in slide-in-from-top-2 duration-200">
            <Label for="sse_url">{{ t('tools.sseUrl') }}</Label>
            <Input
              id="sse_url"
              v-model="form.sse_url"
              type="url"
              :placeholder="t('tools.enterSseUrl')"
              required
            />
          </div>

          <div v-if="form.protocol === 'streamable_http'" class="space-y-2 animate-in slide-in-from-top-2 duration-200">
            <Label for="streamable_http_url">{{ t('tools.streamingHttpUrl') }}</Label>
            <Input
              id="streamable_http_url"
              v-model="form.streamable_http_url"
              type="url"
              :placeholder="t('tools.enterStreamingHttpUrl')"
              required
            />
          </div>
        </div>

        <div v-else class="space-y-6">
          <div class="space-y-4">
            <div class="rounded-2xl border border-primary/20 bg-primary/5 p-4">
              <div class="flex items-center gap-3">
                <div class="rounded-full bg-primary/10 p-2 text-primary">
                  <WandSparkles class="h-5 w-5" />
                </div>
                <div>
                  <h3 class="text-lg font-semibold">{{ t('tools.anyToolEditor') || 'AnyTool Editor' }}</h3>
                  <p class="text-sm text-muted-foreground">
                    {{ t('tools.anyToolEditorHint') || 'Define simulated tools, preview them, and keep the built-in MCP server enabled or disabled.' }}
                  </p>
                </div>
              </div>
            </div>
            <h3 class="flex items-center gap-2 text-lg font-semibold">
              <WandSparkles class="w-5 h-5" />
              {{ t('tools.toolDefinitions') || 'Tool Definitions' }}
            </h3>
          </div>

          <div class="space-y-4">
            <div class="flex items-center justify-between gap-3">
              <Label class="text-base font-medium">{{ t('tools.toolDefinitions') || 'Tool Definitions' }}</Label>
              <Button type="button" variant="outline" size="sm" @click="addTool">
                <Plus class="h-4 w-4 mr-2" />
                {{ t('tools.addTool') || 'Add Tool' }}
              </Button>
            </div>

            <div v-if="form.tools.length === 0" class="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
              {{ t('tools.noAnyToolDefinitions') || 'No tool definitions yet. Add one to start simulating.' }}
            </div>

            <div v-for="(tool, index) in form.tools" :key="tool.id" class="rounded-xl border bg-card p-4 space-y-4">
              <div class="flex items-center justify-between">
                <div class="font-medium">{{ t('tools.toolIndex') || 'Tool' }} {{ index + 1 }}</div>
                <Button type="button" variant="ghost" size="sm" class="text-destructive hover:text-destructive" @click="removeTool(index)">
                  <Trash2 class="h-4 w-4 mr-2" />
                  {{ t('tools.remove') || 'Remove' }}
                </Button>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label>{{ t('tools.toolName') || 'Tool Name' }}</Label>
                  <Input
                    v-model="tool.name"
                    type="text"
                    :placeholder="t('tools.toolNamePlaceholder') || 'search_customer'"
                    required
                  />
                </div>
                <div class="space-y-2">
                  <Label>{{ t('tools.toolDescription') || 'Description' }}</Label>
                  <Input
                    v-model="tool.description"
                    type="text"
                    :placeholder="t('tools.toolDescriptionPlaceholder') || 'Search customers by keyword'"
                  />
                </div>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-3 rounded-xl border bg-muted/10 p-4">
                  <div class="flex items-center justify-between gap-3">
                  <div>
                    <Label class="text-base font-medium">{{ t('tools.parametersSchema') || 'Parameters Schema' }}</Label>
                    <p class="text-xs text-muted-foreground">{{ t('tools.schemaBuilderHint') || 'Build the input schema visually.' }}</p>
                  </div>
                    <Button type="button" variant="outline" size="sm" @click="addBuilderField(tool, 'parametersBuilder')">
                      <Plus class="h-4 w-4 mr-2" />
                      {{ t('tools.addField') || 'Add Field' }}
                    </Button>
                  </div>
                  <div v-if="tool.parametersBuilder.length === 0" class="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                    {{ t('tools.noSchemaFields') || 'No fields yet.' }}
                  </div>
                  <AnyToolSchemaFieldEditor
                    v-for="(field, fieldIndex) in tool.parametersBuilder"
                    :key="field.id"
                    :field="field"
                    :index="fieldIndex"
                    :title="`${t('tools.field') || 'Field'} ${fieldIndex + 1}`"
                    @remove="removeBuilderField(tool, 'parametersBuilder', fieldIndex)"
                  />
                  <details class="rounded-lg border bg-background/60 p-3">
                    <summary class="cursor-pointer text-xs font-medium text-muted-foreground">
                      {{ t('tools.schemaPreview') || 'Schema Preview' }}
                    </summary>
                    <pre class="mt-3 rounded-md bg-muted p-3 overflow-x-auto text-xs font-mono whitespace-pre-wrap">{{ getSchemaPreviewText(tool, 'parametersBuilder') }}</pre>
                  </details>
                </div>
                <div class="space-y-3 rounded-xl border bg-muted/10 p-4">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <Label class="text-base font-medium">{{ t('tools.returnsSchema') || 'Returns Schema' }}</Label>
                      <p class="text-xs text-muted-foreground">{{ t('tools.schemaBuilderHint') || 'Build the output schema visually.' }}</p>
                    </div>
                    <Button type="button" variant="outline" size="sm" @click="addBuilderField(tool, 'returnsBuilder')">
                      <Plus class="h-4 w-4 mr-2" />
                      {{ t('tools.addField') || 'Add Field' }}
                    </Button>
                  </div>
                  <div v-if="tool.returnsBuilder.length === 0" class="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                    {{ t('tools.noSchemaFields') || 'No fields yet.' }}
                  </div>
                  <AnyToolSchemaFieldEditor
                    v-for="(field, fieldIndex) in tool.returnsBuilder"
                    :key="field.id"
                    :field="field"
                    :index="fieldIndex"
                    :title="`${t('tools.field') || 'Field'} ${fieldIndex + 1}`"
                    @remove="removeBuilderField(tool, 'returnsBuilder', fieldIndex)"
                  />
                  <details class="rounded-lg border bg-background/60 p-3">
                    <summary class="cursor-pointer text-xs font-medium text-muted-foreground">
                      {{ t('tools.schemaPreview') || 'Schema Preview' }}
                    </summary>
                    <pre class="mt-3 rounded-md bg-muted p-3 overflow-x-auto text-xs font-mono whitespace-pre-wrap">{{ getSchemaPreviewText(tool, 'returnsBuilder') }}</pre>
                  </details>
                </div>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-2">
                  <Label>{{ t('tools.promptTemplate') || 'Prompt Template' }}</Label>
                  <Textarea
                    v-model="tool.prompt_template"
                    rows="5"
                    class="font-mono text-sm"
                    :placeholder="t('tools.promptTemplatePlaceholder') || 'Use this as extra simulation guidance...'"
                  />
                </div>
                <div class="space-y-2">
                  <Label>{{ t('tools.toolNotes') || 'Notes' }}</Label>
                  <Textarea
                    v-model="tool.notes"
                    rows="5"
                    class="font-mono text-sm"
                    :placeholder="t('tools.toolNotesPlaceholder') || 'Optional notes for future editors'"
                  />
                </div>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-2">
                  <Label>{{ t('tools.exampleInput') || 'Example Input (JSON)' }}</Label>
                  <Textarea
                    v-model="tool.example_input_text"
                    rows="5"
                    class="font-mono text-sm"
                    :placeholder="t('tools.exampleInputPlaceholder') || JSON.stringify({ query: 'acme' }, null, 2)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>{{ t('tools.exampleOutput') || 'Example Output (JSON)' }}</Label>
                  <Textarea
                    v-model="tool.example_output_text"
                    rows="5"
                    class="font-mono text-sm"
                    :placeholder="t('tools.exampleOutputPlaceholder') || JSON.stringify({ results: ['...'] }, null, 2)"
                  />
                </div>
              </div>

              <div class="space-y-3 rounded-lg border bg-muted/20 p-4">
                <div class="flex items-center justify-between gap-3">
                  <Label class="text-sm font-medium">{{ t('tools.toolTest') || 'Tool Test' }}</Label>
                  <Button type="button" size="sm" :disabled="tool.test_loading" @click="runDraftToolTest(tool)">
                    <Loader v-if="tool.test_loading" class="mr-2 h-4 w-4 animate-spin" />
                    <Play v-else class="mr-2 h-4 w-4" />
                    {{ t('tools.runTest') || 'Run Test' }}
                  </Button>
                </div>
                <div v-if="getToolTestFields(tool).length === 0" class="text-xs text-muted-foreground">
                  {{ t('tools.noParameters') }}
                </div>
                <div v-else class="grid gap-3 md:grid-cols-2">
                  <div v-for="field in getToolTestFields(tool)" :key="field.name" class="space-y-2 rounded-md border bg-background p-3">
                    <div class="flex items-center justify-between gap-2">
                      <Label class="text-xs font-medium">{{ field.name }}</Label>
                      <Badge variant="outline" class="text-[10px] font-mono">{{ field.type }}</Badge>
                    </div>
                    <Input
                      v-if="field.kind === 'text'"
                      v-model="tool.test_values[field.name]"
                      :type="field.inputType"
                      :placeholder="field.placeholder"
                    />
                    <Textarea
                      v-else-if="field.kind === 'json'"
                      v-model="tool.test_values[field.name]"
                      rows="4"
                      class="font-mono text-sm"
                      :placeholder="field.placeholder"
                    />
                    <div v-else-if="field.kind === 'boolean'" class="flex items-center justify-between rounded-md border px-3 py-2">
                      <span class="text-xs text-muted-foreground">{{ field.description }}</span>
                      <Switch :checked="tool.test_values[field.name]" @update:checked="(val) => tool.test_values[field.name] = val" />
                    </div>
                    <div v-else-if="field.kind === 'enum'" class="space-y-2">
                      <Select v-model="tool.test_values[field.name]">
                        <SelectTrigger>
                          <SelectValue :placeholder="field.placeholder" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem v-for="item in field.enumValues" :key="item" :value="String(item)">{{ String(item) }}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <p v-if="field.description" class="text-[11px] text-muted-foreground">{{ field.description }}</p>
                  </div>
                </div>
                <div v-if="tool.test_error" class="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  {{ tool.test_error }}
                </div>
                <div v-if="tool.test_result" class="space-y-2">
                  <div class="space-y-1">
                    <Label class="text-xs text-muted-foreground">{{ tr('toolDetail.result', 'Result') }}</Label>
                    <pre class="rounded-md bg-background p-3 overflow-x-auto text-xs font-mono whitespace-pre-wrap">{{ formatTestResultText(tool.test_result) }}</pre>
                  </div>
                  <details v-if="hasRawTestResult(tool.test_result)" class="rounded-md border bg-background/60 p-3">
                    <summary class="cursor-pointer text-xs font-medium text-muted-foreground">
                      {{ tr('toolDetail.rawResponse', 'Raw Response') }}
                    </summary>
                    <pre class="mt-2 rounded-md bg-muted p-3 overflow-x-auto text-xs font-mono whitespace-pre-wrap">{{ tool.test_result.raw_text }}</pre>
                  </details>
                </div>
              </div>
            </div>
          </div>

          <div class="space-y-4">
            <h3 class="flex items-center gap-2 text-lg font-semibold">
              <Sparkles class="w-5 h-5" />
              {{ t('tools.simulatorConfig') || 'Simulator Config' }}
            </h3>
              <div class="grid gap-4 md:grid-cols-2">
                <div class="space-y-2">
                  <Label>{{ t('tools.model') || 'Model' }}</Label>
                  <Input
                    v-model="form.simulator.model"
                    type="text"
                    :placeholder="t('tools.modelPlaceholder') || 'gpt-4.1-mini'"
                  />
                </div>
                <div class="space-y-2">
                  <Label>{{ t('tools.baseUrl') || 'Base URL' }}</Label>
                  <Input
                    v-model="form.simulator.base_url"
                    type="url"
                    :placeholder="t('tools.baseUrlPlaceholder') || 'https://api.openai.com/v1'"
                  />
                </div>
                <div class="space-y-2">
                  <Label>{{ t('tools.apiKey') || 'API Key' }}</Label>
                  <Input
                    v-model="form.simulator.api_key"
                    type="password"
                    :placeholder="t('tools.apiKeyPlaceholder') || 'sk-...'"
                  />
                </div>
                <div class="space-y-2">
                  <Label>{{ t('tools.temperature') || 'Temperature' }}</Label>
                  <Input
                    v-model="form.simulator.temperature"
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    :placeholder="t('tools.temperaturePlaceholder') || '0.2'"
                  />
                </div>
              </div>
              <div class="space-y-2">
                <Label>{{ t('tools.systemPrompt') || 'System Prompt' }}</Label>
              <Textarea
                v-model="form.simulator.system_prompt"
                rows="5"
                class="font-mono text-sm"
                :placeholder="t('tools.systemPromptPlaceholder') || 'You are a tool simulator...'"
              />
              </div>
          </div>
        </div>

        <div class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Globe class="w-5 h-5" />
            {{ t('tools.additionalInfo') }}
          </h3>

          <div class="space-y-2">
            <Label for="description">{{ t('tools.description') }}</Label>
            <Textarea
              id="description"
              v-model="form.description"
              :placeholder="t('tools.enterDescription')"
              rows="4"
              class="resize-y min-h-[100px]"
            />
          </div>
        </div>

        <div class="flex justify-center gap-4 pt-6 border-t">
          <Button type="button" variant="outline" @click="$emit('cancel')">
            {{ t('tools.cancel') }}
          </Button>
          <Button type="submit" :disabled="loading">
            <Loader v-if="loading" class="mr-2 h-4 w-4 animate-spin" />
            {{ loading ? (isEdit ? t('tools.saving') : t('tools.adding')) : (isEdit ? t('tools.save') : t('tools.add')) }}
          </Button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { Database, Code, Globe, Loader, Plus, Trash2, Sparkles, WandSparkles, Play } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { toolAPI } from '@/api/tool.js'
import AnyToolSchemaFieldEditor from '@/components/AnyToolSchemaFieldEditor.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  },
  isEdit: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['submit', 'cancel'])
const { t } = useLanguage()

const newToolTemplate = () => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  name: '',
  description: '',
  parametersBuilder: [],
  returnsBuilder: [],
  prompt_template: '',
  notes: '',
  example_input_text: '{}',
  example_output_text: '{}',
  test_values: {},
  test_result: null,
  test_error: '',
  test_loading: false
})

const form = reactive({
  name: '',
  kind: 'external',
  protocol: 'sse',
  command: '',
  args: '',
  sse_url: '',
  streamable_http_url: '',
  description: '',
  tools: [newToolTemplate()],
  simulator: {
    model: '',
    base_url: '',
    api_key: '',
    temperature: '0.2',
    system_prompt: ''
  }
})

const addTool = () => {
  form.tools.push(newToolTemplate())
}

const removeTool = (index) => {
  form.tools.splice(index, 1)
  if (form.tools.length === 0) {
    form.tools.push(newToolTemplate())
  }
}

const parseJson = (text, fallback) => {
  const raw = (text || '').trim()
  if (!raw) return fallback
  return JSON.parse(raw)
}

const createSchemaField = (overrides = {}) => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  name: '',
  type: 'string',
  description: '',
  required: false,
  defaultValue: '',
  enumText: '',
  itemsType: 'string',
  childrenBuilder: [],
  ...overrides,
})

const normalizeSchemaObject = (schema) => {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) {
    return { type: 'object', properties: {}, required: [] }
  }
  const properties = schema.properties && typeof schema.properties === 'object' ? schema.properties : {}
  const required = Array.isArray(schema.required) ? schema.required : []
  return {
    ...schema,
    type: schema.type === 'object' ? 'object' : 'object',
    properties,
    required,
  }
}

const schemaToBuilderFields = (schema) => {
  const normalized = normalizeSchemaObject(schema)
  const requiredSet = new Set(normalized.required || [])
  return Object.entries(normalized.properties || {}).map(([name, propSchema]) => {
    const prop = propSchema && typeof propSchema === 'object' ? propSchema : {}
    const type = prop.type || 'string'
    const enumValues = Array.isArray(prop.enum) ? prop.enum : []
    const nestedSource = type === 'object'
      ? prop
      : (type === 'array' && prop.items && typeof prop.items === 'object' && prop.items.type === 'object')
        ? prop.items
        : null
    return createSchemaField({
      name,
      type,
      description: prop.description || '',
      required: requiredSet.has(name),
      defaultValue: prop.default != null ? String(prop.default) : '',
      enumText: enumValues.join('\n'),
      itemsType: prop.items && typeof prop.items === 'object' && prop.items.type ? prop.items.type : 'string',
      childrenBuilder: nestedSource ? schemaToBuilderFields(nestedSource) : [],
    })
  })
}

const parseDefaultValue = (field) => {
  const raw = field.defaultValue
  if (raw === '' || raw == null) return undefined
  switch (field.type) {
    case 'number':
      return Number(raw)
    case 'integer':
      return parseInt(String(raw), 10)
    case 'boolean':
      return raw === true || raw === 'true'
    case 'array':
    case 'object':
      try {
        return JSON.parse(String(raw))
      } catch {
        return undefined
      }
    default:
      return String(raw)
  }
}

const buildSchemaFromBuilder = (fields) => {
  const properties = {}
  const required = []
  for (const field of Array.isArray(fields) ? fields : []) {
    const name = String(field.name || '').trim()
    if (!name) continue

    const type = field.type || 'string'
    const schema = {
      type,
    }
    if (field.description) {
      schema.description = field.description
    }
    const defaultValue = parseDefaultValue(field)
    if (defaultValue !== undefined) {
      schema.default = defaultValue
    }
    if (field.enumText && String(field.enumText).trim()) {
      schema.enum = String(field.enumText)
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean)
    }
    if (type === 'array') {
      if (field.itemsType === 'object') {
        schema.items = buildSchemaFromBuilder(field.childrenBuilder || [])
      } else {
        schema.items = { type: field.itemsType || 'string' }
      }
    }
    if (type === 'object') {
      const nested = buildSchemaFromBuilder(field.childrenBuilder || [])
      schema.properties = nested.properties
      schema.required = nested.required
    }
    properties[name] = schema
    if (field.required) {
      required.push(name)
    }
  }
  return { type: 'object', properties, required }
}

const schemaToPrettyText = (fields) => {
  return JSON.stringify(buildSchemaFromBuilder(fields), null, 2)
}

const tr = (key, fallback) => {
  const translated = t(key)
  return translated === key ? fallback : translated
}

const getToolTestFields = (tool) => {
  try {
    const schema = buildSchemaFromBuilder(tool.parametersBuilder)
    const properties = schema.properties && typeof schema.properties === 'object' ? schema.properties : {}
    return Object.entries(properties).map(([name, propSchema]) => {
      const normalized = propSchema && typeof propSchema === 'object' ? propSchema : {}
      const type = normalized.type || 'string'
      const enumValues = Array.isArray(normalized.enum) ? normalized.enum : []
      const kind = enumValues.length > 0
        ? 'enum'
        : (type === 'object' || type === 'array')
          ? 'json'
          : type === 'boolean'
            ? 'boolean'
            : 'text'
      const placeholderMap = {
        string: '请输入文本',
        number: '请输入数字',
        integer: '请输入整数',
        boolean: 'true / false',
        object: '{"key":"value"}',
        array: '["item"]',
      }
      return {
        name,
        type,
        kind,
        enumValues,
        description: normalized.description || '',
        placeholder: normalized.enum ? '请选择' : (placeholderMap[type] || '请输入'),
        inputType: type === 'number' || type === 'integer' ? 'number' : 'text',
      }
    })
  } catch (error) {
    return []
  }
}

const buildToolArguments = (tool) => {
  const payload = {}
  for (const field of getToolTestFields(tool)) {
    const value = tool.test_values?.[field.name]
    if (field.kind === 'boolean') {
      payload[field.name] = Boolean(value)
      continue
    }
    if (field.kind === 'json') {
      const raw = typeof value === 'string' ? value.trim() : ''
      if (!raw) {
        payload[field.name] = field.type === 'array' ? [] : {}
        continue
      }
      payload[field.name] = JSON.parse(raw)
      continue
    }
    if (field.kind === 'enum') {
      payload[field.name] = value
      continue
    }
    if (field.type === 'integer') {
      payload[field.name] = value === '' ? null : parseInt(String(value), 10)
      continue
    }
    if (field.type === 'number') {
      payload[field.name] = value === '' ? null : Number(value)
      continue
    }
    payload[field.name] = value
  }
  return payload
}

const formatTestResultText = (result) => {
  if (!result) return ''
  if (typeof result.formatted_text === 'string' && result.formatted_text.trim()) {
    return result.formatted_text
  }
  if (typeof result.parsed === 'string') {
    return result.parsed
  }
  if (result.parsed && typeof result.parsed === 'object') {
    return JSON.stringify(result.parsed, null, 2)
  }
  if (typeof result.raw_text === 'string') {
    return result.raw_text
  }
  return JSON.stringify(result, null, 2)
}

const hasRawTestResult = (result) => {
  return result?.raw_text && result.raw_text !== formatTestResultText(result)
}

const buildSingleToolDefinition = (tool) => {
  const parameters = buildSchemaFromBuilder(tool.parametersBuilder)
  const returns = buildSchemaFromBuilder(tool.returnsBuilder)
  return {
    name: tool.name,
    description: tool.description,
    parameters,
    returns,
    prompt_template: tool.prompt_template,
    notes: tool.notes,
    example_input: parseJson(tool.example_input_text, {}),
    example_output: parseJson(tool.example_output_text, {}),
  }
}

const runDraftToolTest = async (tool) => {
  try {
    tool.test_loading = true
    tool.test_error = ''
    tool.test_result = null

    const argumentsPayload = buildToolArguments(tool)
    const response = await toolAPI.previewAnyToolDraft({
      server_name: form.name || 'draft',
      tool_definition: buildSingleToolDefinition(tool),
      arguments: argumentsPayload,
      simulator: {
        model: form.simulator.model,
        base_url: form.simulator.base_url,
        api_key: form.simulator.api_key,
        temperature: form.simulator.temperature ? Number(form.simulator.temperature) : 0.2,
        system_prompt: form.simulator.system_prompt,
      },
    })
    tool.test_result = response
  } catch (error) {
    const message = String(error?.message || '')
    if (message.includes('ECONNREFUSED') || message.includes('Failed to fetch')) {
      tool.test_error = t('tools.previewBackendUnavailable') || 'Preview backend is unavailable. Start the Sage backend and try again.'
    } else {
      tool.test_error = message || (t('tools.previewFailed') || 'Preview failed')
    }
  } finally {
    tool.test_loading = false
  }
}

const buildAnyToolPayload = () => {
  return form.tools
    .map((tool) => {
      const parameters = buildSchemaFromBuilder(tool.parametersBuilder)
      const returns = buildSchemaFromBuilder(tool.returnsBuilder)
      const exampleInput = parseJson(tool.example_input_text, {})
      const exampleOutput = parseJson(tool.example_output_text, {})
      return {
        name: tool.name,
        description: tool.description,
        parameters,
        returns,
        prompt_template: tool.prompt_template,
        notes: tool.notes,
        example_input: exampleInput,
        example_output: exampleOutput,
      }
    })
    .filter((item) => item.name)
}

const addBuilderField = (tool, key) => {
  tool[key].push(createSchemaField())
}

const removeBuilderField = (tool, key, index) => {
  tool[key].splice(index, 1)
}

const getSchemaPreviewText = (tool, key) => {
  return schemaToPrettyText(tool[key])
}

const handleSubmit = () => {
  try {
    const payload = {
      name: form.kind === 'anytool' ? 'AnyTool' : form.name,
      kind: form.kind,
      protocol: form.kind === 'anytool' ? 'streamable_http' : form.protocol,
      description: form.description
    }

    if (form.kind === 'external') {
      if (form.protocol === 'stdio') {
        payload.command = form.command
        if (form.args) {
          payload.args = Array.isArray(form.args)
            ? form.args
            : form.args.split(' ').filter(arg => arg.trim())
        }
      } else if (form.protocol === 'sse') {
        payload.sse_url = form.sse_url
      } else if (form.protocol === 'streamable_http') {
        payload.streamable_http_url = form.streamable_http_url
      }
    } else {
      payload.tools = buildAnyToolPayload()
      payload.simulator = {
        model: form.simulator.model,
        base_url: form.simulator.base_url,
        api_key: form.simulator.api_key,
        temperature: form.simulator.temperature ? Number(form.simulator.temperature) : 0.2,
        system_prompt: form.simulator.system_prompt,
      }
    }

    emit('submit', payload)
  } catch (error) {
    console.error('Failed to build MCP payload:', error)
    alert(error.message || 'Invalid JSON in AnyTool configuration')
  }
}

const setFormData = (data) => {
  form.name = data.name || ''
  form.kind = 'external'
  form.protocol = data.protocol || 'sse'
  form.description = data.description || ''

  form.command = data.command || ''
  form.args = Array.isArray(data.args) ? data.args.join(' ') : (data.args || '')
  form.sse_url = data.sse_url || ''
  form.streamable_http_url = data.streamable_http_url || ''

  const tools = Array.isArray(data.tools) && data.tools.length ? data.tools : [newToolTemplate()]
  form.tools = tools.map((tool) => ({
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    name: tool.name || '',
    description: tool.description || '',
    parametersBuilder: schemaToBuilderFields(tool.parameters || { type: 'object', properties: {}, required: [] }),
    returnsBuilder: schemaToBuilderFields(tool.returns || { type: 'object', properties: {}, required: [] }),
    prompt_template: tool.prompt_template || tool.prompt || '',
    notes: tool.notes || '',
    example_input_text: JSON.stringify(tool.example_input || {}, null, 2),
    example_output_text: JSON.stringify(tool.example_output || {}, null, 2),
    test_values: { ...(tool.example_input || {}) },
    test_result: null,
    test_error: '',
    test_loading: false
  }))

  const simulator = data.simulator || {}
  form.simulator.model = simulator.model || ''
  form.simulator.base_url = simulator.base_url || ''
  form.simulator.api_key = simulator.api_key || ''
  form.simulator.temperature = simulator.temperature != null ? String(simulator.temperature) : '0.2'
  form.simulator.system_prompt = simulator.system_prompt || ''
}

const resetForm = () => {
  form.name = ''
  form.kind = 'external'
  form.protocol = 'sse'
  form.command = ''
  form.args = ''
  form.sse_url = ''
  form.streamable_http_url = ''
  form.description = ''
  form.tools = [newToolTemplate()]
  form.simulator = {
    model: '',
    base_url: '',
    api_key: '',
    temperature: '0.2',
    system_prompt: ''
  }
}

defineExpose({
  resetForm,
  setFormData,
  addTool
})
</script>
