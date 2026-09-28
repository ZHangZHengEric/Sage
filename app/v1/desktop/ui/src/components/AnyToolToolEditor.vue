<template>
  <div class="w-full h-full p-4 overflow-y-auto">
    <div class="max-w-4xl mx-auto">
      <form @submit.prevent="handleSubmit" class="space-y-8 pb-10">
        <div class="rounded-2xl border border-primary/20 bg-primary/5 p-4">
          <div class="flex items-center gap-3">
            <div class="rounded-full bg-primary/10 p-2 text-primary">
              <WandSparkles class="h-5 w-5" />
            </div>
            <div>
              <h3 class="text-lg font-semibold">
                {{ tr('tools.anyToolToolEditor', 'AnyTool Tool Editor') }}
              </h3>
              <p class="text-sm text-muted-foreground">
                {{ tr('tools.anyToolToolEditorHint', 'Define a single simulated tool, then preview or save it into AnyTool.') }}
              </p>
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <h3 class="flex items-center gap-2 text-lg font-semibold">
            <Sparkles class="w-5 h-5" />
            {{ tr('tools.toolDefinitions', 'Tool Definition') }}
          </h3>

          <div class="grid gap-4 md:grid-cols-2">
            <div class="space-y-2">
              <Label>{{ tr('tools.toolName', 'Tool Name') }}</Label>
              <Input
                v-model="form.name"
                type="text"
                :placeholder="tr('tools.toolNamePlaceholder', 'search_customer')"
                required
              />
              <p v-if="hasInvalidToolName()" class="text-xs text-destructive">
                {{ tr('tools.toolNameNoSpaces', 'Tool names cannot contain spaces') }}
              </p>
            </div>
            <div class="space-y-2">
              <Label>{{ tr('tools.toolDescription', 'Description') }}</Label>
              <Input
                v-model="form.description"
                type="text"
                :placeholder="tr('tools.toolDescriptionPlaceholder', 'Search customers by keyword')"
              />
            </div>
          </div>
        </div>

        <div class="grid gap-4 lg:grid-cols-2">
          <div class="space-y-3 rounded-xl border bg-muted/10 p-4">
            <div class="flex items-center justify-between gap-3">
              <div>
                <Label class="text-base font-medium">{{ tr('tools.parametersSchema', 'Parameters Schema') }}</Label>
                <p class="text-xs text-muted-foreground">{{ tr('tools.schemaBuilderHint', 'Build the input schema visually.') }}</p>
              </div>
              <Button type="button" variant="outline" size="sm" @click="addBuilderField('parametersBuilder')">
                <Plus class="h-4 w-4 mr-2" />
                {{ tr('tools.addField', 'Add Field') }}
              </Button>
            </div>
            <div v-if="form.parametersBuilder.length === 0" class="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                {{ tr('tools.noSchemaFields', 'No fields yet.') }}
            </div>
            <AnyToolSchemaFieldEditor
              v-for="(field, fieldIndex) in form.parametersBuilder"
              :key="field.id"
              :field="field"
              :index="fieldIndex"
              :title="`${tr('tools.field', 'Field')} ${fieldIndex + 1}`"
              @remove="removeBuilderField('parametersBuilder', fieldIndex)"
            />
            <details class="rounded-lg border bg-background/60 p-3">
              <summary class="cursor-pointer text-xs font-medium text-muted-foreground">
                {{ tr('tools.schemaPreview', 'Schema Preview') }}
              </summary>
              <pre class="mt-3 rounded-md bg-muted p-3 overflow-x-auto text-xs font-mono whitespace-pre-wrap">{{ getSchemaPreviewText('parametersBuilder') }}</pre>
            </details>
          </div>

          <div class="space-y-3 rounded-xl border bg-muted/10 p-4">
            <div class="flex items-center justify-between gap-3">
              <div>
                <Label class="text-base font-medium">{{ tr('tools.returnsSchema', 'Returns Schema') }}</Label>
                <p class="text-xs text-muted-foreground">{{ tr('tools.schemaBuilderHint', 'Build the output schema visually.') }}</p>
              </div>
              <Button type="button" variant="outline" size="sm" @click="addBuilderField('returnsBuilder')">
                <Plus class="h-4 w-4 mr-2" />
                {{ tr('tools.addField', 'Add Field') }}
              </Button>
            </div>
            <div v-if="form.returnsBuilder.length === 0" class="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                {{ tr('tools.noSchemaFields', 'No fields yet.') }}
            </div>
            <AnyToolSchemaFieldEditor
              v-for="(field, fieldIndex) in form.returnsBuilder"
              :key="field.id"
              :field="field"
              :index="fieldIndex"
              :title="`${tr('tools.field', 'Field')} ${fieldIndex + 1}`"
              @remove="removeBuilderField('returnsBuilder', fieldIndex)"
            />
            <details class="rounded-lg border bg-background/60 p-3">
              <summary class="cursor-pointer text-xs font-medium text-muted-foreground">
                {{ tr('tools.schemaPreview', 'Schema Preview') }}
              </summary>
              <pre class="mt-3 rounded-md bg-muted p-3 overflow-x-auto text-xs font-mono whitespace-pre-wrap">{{ getSchemaPreviewText('returnsBuilder') }}</pre>
            </details>
          </div>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-2">
            <Label>{{ tr('tools.promptTemplate', 'Prompt Template') }}</Label>
            <Textarea
              v-model="form.prompt_template"
              rows="5"
              class="font-mono text-sm"
              :placeholder="tr('tools.promptTemplatePlaceholder', 'Use this as extra simulation guidance...')"
            />
          </div>
          <div class="space-y-2">
            <Label>{{ tr('tools.toolNotes', 'Notes') }}</Label>
            <Textarea
              v-model="form.notes"
              rows="5"
              class="font-mono text-sm"
              :placeholder="tr('tools.toolNotesPlaceholder', 'Optional notes for future editors')"
            />
          </div>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-2">
            <Label>{{ tr('tools.exampleInput', 'Example Input (JSON)') }}</Label>
            <Textarea
              v-model="form.example_input_text"
              rows="5"
              class="font-mono text-sm"
              :placeholder="tr('tools.exampleInputPlaceholder', JSON.stringify({ query: 'acme' }, null, 2))"
            />
          </div>
          <div class="space-y-2">
            <Label>{{ tr('tools.exampleOutput', 'Example Output (JSON)') }}</Label>
            <Textarea
              v-model="form.example_output_text"
              rows="5"
              class="font-mono text-sm"
              :placeholder="tr('tools.exampleOutputPlaceholder', JSON.stringify({ results: ['...'] }, null, 2))"
            />
          </div>
        </div>

        <div class="space-y-3 rounded-lg border bg-muted/20 p-4">
          <div class="flex items-center justify-between gap-3">
            <Label class="text-sm font-medium">{{ tr('tools.toolTest', 'Tool Test') }}</Label>
            <Button type="button" size="sm" :disabled="form.test_loading" @click="runDraftToolTest">
              <Loader v-if="form.test_loading" class="mr-2 h-4 w-4 animate-spin" />
              <Play v-else class="mr-2 h-4 w-4" />
              {{ tr('tools.runTest', 'Run Test') }}
            </Button>
          </div>
          <div v-if="getToolTestFields().length === 0" class="text-xs text-muted-foreground">
            {{ tr('tools.noParameters', 'No parameters') }}
          </div>
          <div v-else class="grid gap-3 md:grid-cols-2">
            <div v-for="field in getToolTestFields()" :key="field.name" class="space-y-2 rounded-md border bg-background p-3">
              <div class="flex items-center justify-between gap-2">
                <Label class="text-xs font-medium">{{ field.name }}</Label>
                <Badge variant="outline" class="text-[10px] font-mono">{{ field.type }}</Badge>
              </div>
              <Input
                v-if="field.kind === 'text'"
                v-model="form.test_values[field.name]"
                :type="field.inputType"
                :placeholder="field.placeholder"
              />
              <Textarea
                v-else-if="field.kind === 'json'"
                v-model="form.test_values[field.name]"
                rows="5"
                class="font-mono text-sm"
                :placeholder="field.placeholder"
              />
              <div v-else-if="field.kind === 'boolean'" class="flex items-center justify-between rounded-md border bg-background px-3 py-2">
                <span class="text-sm text-muted-foreground">{{ field.description }}</span>
                <Switch :checked="form.test_values[field.name]" @update:checked="(val) => form.test_values[field.name] = val" />
              </div>
              <div v-else-if="field.kind === 'enum'" class="space-y-2">
                <Select v-model="form.test_values[field.name]">
                  <SelectTrigger>
                    <SelectValue :placeholder="field.placeholder" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="item in field.enumValues" :key="item" :value="String(item)">{{ String(item) }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <p v-if="field.description" class="text-xs text-muted-foreground">{{ field.description }}</p>
            </div>
          </div>

        <div v-if="form.test_error" class="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {{ form.test_error }}
        </div>

          <div v-if="form.test_result" class="space-y-3">
            <div class="space-y-2">
              <Label class="text-sm font-medium">{{ tr('tools.previewResult', 'Result') }}</Label>
              <pre class="rounded-lg bg-muted p-4 overflow-x-auto text-sm font-mono text-muted-foreground whitespace-pre-wrap">{{ formatTestResultText(form.test_result) }}</pre>
            </div>
            <details v-if="hasRawTestResult(form.test_result)" class="rounded-lg border bg-background/60 p-3">
              <summary class="cursor-pointer text-sm font-medium text-muted-foreground">
                {{ tr('tools.rawResponse', 'Raw Response') }}
              </summary>
              <pre class="mt-3 rounded-md bg-muted p-4 overflow-x-auto text-sm font-mono text-muted-foreground whitespace-pre-wrap">{{ form.test_result.raw_text }}</pre>
            </details>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 border-t pt-4">
          <Button type="button" variant="outline" @click="$emit('cancel')">
            {{ tr('common.cancel', tr('tools.cancel', 'Cancel')) }}
          </Button>
          <Button type="submit" :disabled="loading || !String(form.name || '').trim() || hasInvalidToolName()">
            <Loader v-if="loading" class="mr-2 h-4 w-4 animate-spin" />
            {{ mode === 'edit' ? tr('tools.saveChanges', 'Save Changes') : tr('tools.createTool', 'Create Tool') }}
          </Button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { reactive, watch } from 'vue'
import { Loader, Play, Plus, Sparkles, WandSparkles } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { toolAPI } from '@/api/tool.js'
import AnyToolSchemaFieldEditor from '@/components/AnyToolSchemaFieldEditor.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

defineOptions({
  name: 'AnyToolToolEditor'
})

const props = defineProps({
  tool: {
    type: Object,
    default: null
  },
  mode: {
    type: String,
    default: 'create'
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['submit', 'cancel'])

const { t } = useLanguage()

const tr = (key, fallback) => {
  const translated = t(key)
  return translated === key ? fallback : translated
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

const createFormState = () => ({
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

const form = reactive(createFormState())

const parseJson = (text, fallback) => {
  const raw = (text || '').trim()
  if (!raw) return fallback
  return JSON.parse(raw)
}

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
    const schema = { type }
    if (field.description) schema.description = field.description
    const defaultValue = parseDefaultValue(field)
    if (defaultValue !== undefined) schema.default = defaultValue
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
    if (field.required) required.push(name)
  }
  return { type: 'object', properties, required }
}

const schemaToPrettyText = (fields) => JSON.stringify(buildSchemaFromBuilder(fields), null, 2)

const getToolTestFields = () => {
  try {
    const schema = buildSchemaFromBuilder(form.parametersBuilder)
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
        string: tr('tools.enterText', 'Enter text'),
        number: tr('tools.enterNumber', 'Enter number'),
        integer: tr('tools.enterInteger', 'Enter integer'),
        boolean: tr('tools.trueFalse', 'true / false'),
        object: tr('tools.jsonObjectPlaceholder', JSON.stringify({ key: 'value' }, null, 2)),
        array: tr('tools.jsonArrayPlaceholder', JSON.stringify(['item'], null, 2)),
      }
      return {
        name,
        type,
        kind,
        enumValues,
        description: normalized.description || '',
        placeholder: normalized.enum ? tr('tools.selectOption', 'Select an option') : (placeholderMap[type] || tr('tools.enterValue', 'Enter value')),
        inputType: type === 'number' || type === 'integer' ? 'number' : 'text',
        defaultValue: normalized.default,
      }
    })
  } catch {
    return []
  }
}

const buildToolArguments = () => {
  const payload = {}
  for (const field of getToolTestFields()) {
    const value = form.test_values?.[field.name]
    if (field.kind === 'boolean') {
      payload[field.name] = Boolean(value)
      continue
    }
    if (field.kind === 'json') {
      const raw = typeof value === 'string' ? value.trim() : ''
      payload[field.name] = raw ? JSON.parse(raw) : (field.type === 'array' ? [] : {})
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

const buildToolDefinition = () => ({
  name: String(form.name || '').trim(),
  description: form.description,
  parameters: buildSchemaFromBuilder(form.parametersBuilder),
  returns: buildSchemaFromBuilder(form.returnsBuilder),
  prompt_template: form.prompt_template,
  notes: form.notes,
  example_input: parseJson(form.example_input_text, {}),
  example_output: parseJson(form.example_output_text, {}),
})

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

const addBuilderField = (key) => {
  form[key].push(createSchemaField())
}

const removeBuilderField = (key, index) => {
  form[key].splice(index, 1)
}

const getSchemaPreviewText = (key) => schemaToPrettyText(form[key])

const hasInvalidToolName = () => {
  const name = String(form.name || '').trim()
  return Boolean(name) && /\s/.test(name)
}

const runDraftToolTest = async () => {
  try {
    form.test_loading = true
    form.test_error = ''
    form.test_result = null
    if (hasInvalidToolName()) {
      form.test_error = tr('tools.toolNameNoSpaces', 'Tool names cannot contain spaces')
      return
    }
    const response = await toolAPI.previewAnyToolDraft({
      server_name: 'draft',
      tool_definition: buildToolDefinition(),
      arguments: buildToolArguments(),
      simulator: {},
    })
    form.test_result = response
  } catch (error) {
    const message = String(error?.message || '')
    if (message.includes('ECONNREFUSED') || message.includes('Failed to fetch')) {
      form.test_error = tr('tools.previewBackendUnavailable', 'Preview backend is unavailable. Start the Sage backend and try again.')
    } else {
      form.test_error = message || tr('tools.previewFailed', 'Preview failed')
    }
  } finally {
    form.test_loading = false
  }
}

const resetForm = () => {
  Object.assign(form, createFormState())
}

const setToolData = (tool) => {
  resetForm()
  const sourceTool = tool || {}
  form.name = sourceTool.name || ''
  form.description = sourceTool.description || ''
  form.parametersBuilder = schemaToBuilderFields(sourceTool.parameters || { type: 'object', properties: {}, required: [] })
  form.returnsBuilder = schemaToBuilderFields(sourceTool.returns || { type: 'object', properties: {}, required: [] })
  form.prompt_template = sourceTool.prompt_template || sourceTool.prompt || ''
  form.notes = sourceTool.notes || ''
  form.example_input_text = JSON.stringify(sourceTool.example_input || {}, null, 2)
  form.example_output_text = JSON.stringify(sourceTool.example_output || {}, null, 2)
  form.test_values = { ...(sourceTool.example_input || {}) }
}

const handleSubmit = () => {
  try {
    const tool_definition = buildToolDefinition()
    if (!tool_definition.name) {
      form.test_error = tr('tools.toolNameRequired', 'Tool name is required')
      return
    }
    if (hasInvalidToolName()) {
      form.test_error = tr('tools.toolNameNoSpaces', 'Tool names cannot contain spaces')
      return
    }
    emit('submit', {
      tool_definition,
      original_name: props.mode === 'edit' ? (props.tool?.name || tool_definition.name) : undefined,
    })
  } catch (error) {
    form.test_error = error.message || tr('tools.saveFailed', 'Failed to save tool')
  }
}

watch(
  () => props.tool,
  (tool) => {
    if (tool) {
      setToolData(tool)
    } else {
      resetForm()
    }
  },
  { immediate: true }
)

defineExpose({
  resetForm,
  setToolData,
})
</script>
