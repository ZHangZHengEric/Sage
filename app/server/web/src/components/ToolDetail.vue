<template>
  <div class="flex h-full flex-col space-y-4 md:space-y-6">
    <!-- 头部信息 -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b gap-4 sm:gap-0">
      <div class="flex items-center gap-4">
        <div 
          class="flex h-12 w-12 items-center justify-center rounded-lg text-white shadow-sm shrink-0"
          :class="getToolTypeColorClass(tool.type)"
        >
          <component :is="getToolIcon(tool.type)" class="h-6 w-6" />
        </div>
        <div class="min-w-0 flex-1">
          <h1 class="text-xl md:text-2xl font-bold tracking-tight truncate">{{ getToolLabel(tool.name, t) }}</h1>
          <Badge :variant="getToolTypeBadgeVariant(tool.type)" class="mt-1">
            {{ getToolTypeLabel(tool.type) }}
          </Badge>
        </div>
      </div>
      <Button variant="outline" @click="$emit('back')" class="w-full sm:w-auto">
        <ArrowLeft class="mr-2 h-4 w-4" />
        {{ t('tools.backToList') }}
      </Button>
      <Button
        v-if="canEditAnyTool"
        variant="outline"
        class="w-full sm:w-auto"
        @click="$emit('edit')"
      >
        <Edit class="mr-2 h-4 w-4" />
        {{ t('tools.editTool') || 'Edit Tool' }}
      </Button>
    </div>

    <ScrollArea class="flex-1 -mr-4 pr-4">
      <div class="space-y-6">
        <!-- 描述 -->
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-lg">
              <Database class="h-5 w-5" />
              {{ t('toolDetail.description') }}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-muted-foreground leading-relaxed">
              {{ tool.description || t('tools.noDescription') }}
            </p>
          </CardContent>
        </Card>

        <!-- 基本信息 -->
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-lg">
              <Code class="h-5 w-5" />
              {{ t('toolDetail.basicInfo') }}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div class="space-y-1">
                <span class="text-sm font-medium text-muted-foreground">{{ t('toolDetail.toolName') }}</span>
                <p class="font-medium">{{ getToolLabel(tool.name, t) }}</p>
              </div>
              <div class="space-y-1">
                <span class="text-sm font-medium text-muted-foreground">{{ t('toolDetail.toolType') }}</span>
                <p class="font-medium">{{ getToolTypeLabel(tool.type) }}</p>
              </div>
              <div class="space-y-1">
                <span class="text-sm font-medium text-muted-foreground">{{ t('toolDetail.source') }}</span>
                <p class="font-medium">{{ getToolSourceLabel(tool.source) }}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <!-- 参数详情 -->
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-lg">
              <Wrench class="h-5 w-5" />
              {{ t('toolDetail.parameterDetails') }}
            </CardTitle>
          </CardHeader>
          <CardContent class="p-0 sm:p-6">
            <div v-if="formattedParams.length > 0" class="rounded-md border overflow-hidden">
              <div class="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead class="w-[150px] sm:w-[200px]">{{ t('toolDetail.paramName') }}</TableHead>
                      <TableHead class="w-[100px] sm:w-[150px]">{{ t('toolDetail.paramType') }}</TableHead>
                      <TableHead class="w-[80px] sm:w-[100px]">{{ t('toolDetail.required') }}</TableHead>
                      <TableHead class="min-w-[200px]">{{ t('toolDetail.paramDescription') }}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    <TableRow v-for="(param, index) in formattedParams" :key="index">
                      <TableCell class="font-medium font-mono text-primary">{{ param.name }}</TableCell>
                      <TableCell>
                        <Badge variant="outline" class="font-mono text-xs whitespace-nowrap">
                          {{ param.type }}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge :variant="param.required ? 'default' : 'secondary'" class="whitespace-nowrap">
                          {{ param.required ? t('toolDetail.yes') : t('toolDetail.no') }}
                        </Badge>
                      </TableCell>
                      <TableCell class="text-muted-foreground">
                        {{ param.description }}
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
            </div>
            <p v-else class="text-sm text-muted-foreground italic p-4 sm:p-0">
              {{ t('toolDetail.noParameters') }}
            </p>
          </CardContent>
        </Card>

        <!-- 原始配置 -->
        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-lg">
              <Globe class="h-5 w-5" />
              {{ t('toolDetail.rawConfig') }}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre class="rounded-lg bg-muted p-4 overflow-x-auto text-sm font-mono text-muted-foreground">{{ JSON.stringify(tool.parameters, null, 2) }}</pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-lg">
              <Sparkles class="h-5 w-5" />
              {{ tr('toolDetail.preview', 'Run Tool') }}
            </CardTitle>
          </CardHeader>
          <CardContent class="space-y-4">
            <div v-if="previewFields.length === 0" class="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              {{ t('toolDetail.noParameters') }}
            </div>
            <div v-else class="grid gap-4 md:grid-cols-2">
              <div v-for="field in previewFields" :key="field.name" class="space-y-2 rounded-lg border bg-muted/20 p-4">
                <div class="flex items-center justify-between gap-2">
                  <Label class="text-sm font-medium">{{ field.name }}</Label>
                  <Badge variant="outline" class="text-[10px] font-mono">{{ field.type }}</Badge>
                </div>
                <Input
                  v-if="field.kind === 'text'"
                  v-model="previewValues[field.name]"
                  :type="field.inputType"
                  :placeholder="field.placeholder"
                />
                <Textarea
                  v-else-if="field.kind === 'json'"
                  v-model="previewValues[field.name]"
                  rows="5"
                  class="font-mono text-sm"
                  :placeholder="field.placeholder"
                />
                <div v-else-if="field.kind === 'boolean'" class="flex items-center justify-between rounded-md border bg-background px-3 py-2">
                  <span class="text-sm text-muted-foreground">{{ field.description }}</span>
                  <Switch :checked="previewValues[field.name]" @update:checked="(val) => previewValues[field.name] = val" />
                </div>
                <div v-else-if="field.kind === 'enum'" class="space-y-2">
                  <Select v-model="previewValues[field.name]">
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
            <div class="flex justify-end">
              <Button type="button" size="sm" :disabled="previewLoading" @click="runPreview">
                <Loader v-if="previewLoading" class="mr-2 h-4 w-4 animate-spin" />
                <Play v-else class="mr-2 h-4 w-4" />
                {{ tr('toolDetail.runPreview', 'Run Test') }}
              </Button>
            </div>

            <div v-if="previewError" class="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
              {{ previewError }}
            </div>

            <div v-if="previewResult" class="space-y-3">
              <div class="space-y-2">
                <Label class="text-sm font-medium">{{ tr('toolDetail.result', 'Result') }}</Label>
                <pre class="rounded-lg bg-muted p-4 overflow-x-auto text-sm font-mono text-muted-foreground whitespace-pre-wrap">{{ previewDisplayText }}</pre>
              </div>
              <details v-if="previewHasRaw" class="rounded-lg border bg-background/60 p-3">
                <summary class="cursor-pointer text-sm font-medium text-muted-foreground">
                  {{ tr('toolDetail.rawResponse', 'Raw Response') }}
                </summary>
                <pre class="mt-3 rounded-md bg-muted p-4 overflow-x-auto text-sm font-mono text-muted-foreground whitespace-pre-wrap">{{ previewDisplayRaw }}</pre>
              </details>
            </div>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ArrowLeft, Database, Code, Wrench, Globe, Cpu, Play, Sparkles, Loader, Edit } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { getMcpServerLabel } from '../utils/mcpLabels.js'
import { getToolLabel } from '../utils/messageLabels.js'
import { toolAPI } from '../api/tool.js'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

// Props
const props = defineProps({
  tool: {
    type: Object,
    required: true
  }
})

// Emits
defineEmits(['back', 'edit'])

// Composables
const { t } = useLanguage()
const previewResult = ref(null)
const previewLoading = ref(false)
const previewError = ref('')
const previewValues = reactive({})

const canEditAnyTool = computed(() => {
  const source = props.tool?.source || ''
  return props.tool?.server_kind === 'anytool' || source === '内置MCP: AnyTool' || source === 'AnyTool'
})

// Computed
const formattedParams = computed(() => {
  if (!props.tool || !props.tool.parameters) {
    return []
  }
  return formatParameters(props.tool.parameters, props.tool.required)
})

const previewFields = computed(() => {
  if (!props.tool || !props.tool.parameters || typeof props.tool.parameters !== 'object') {
    return []
  }

  return Object.entries(props.tool.parameters).map(([name, schema]) => {
    const normalized = schema && typeof schema === 'object' ? schema : {}
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
      string: t('tools.enterText') || 'Enter text',
      number: t('tools.enterNumber') || 'Enter number',
      integer: t('tools.enterInteger') || 'Enter integer',
      boolean: t('tools.trueFalse') || 'true / false',
      object: '{"key":"value"}',
      array: '["item"]',
    }
    return {
      name,
      type,
      kind,
      enumValues,
      description: normalized.description || '',
      placeholder: normalized.enum ? (t('tools.selectOption') || 'Select an option') : (placeholderMap[type] || t('tools.enterValue') || 'Enter value'),
      inputType: type === 'number' || type === 'integer' ? 'number' : 'text',
      defaultValue: normalized.default,
    }
  })
})

watch(
  previewFields,
  (fields) => {
    const nextValues = {}
    for (const field of fields) {
      if (field.kind === 'boolean') {
        nextValues[field.name] = field.defaultValue != null ? Boolean(field.defaultValue) : false
      } else if (field.kind === 'json') {
        if (field.defaultValue != null) {
          nextValues[field.name] = JSON.stringify(field.defaultValue, null, 2)
        } else {
          nextValues[field.name] = field.type === 'array' ? '[]' : '{}'
        }
      } else if (field.kind === 'enum') {
        nextValues[field.name] = field.defaultValue != null ? String(field.defaultValue) : String(field.enumValues[0] ?? '')
      } else if (field.defaultValue != null) {
        nextValues[field.name] = String(field.defaultValue)
      } else {
        nextValues[field.name] = ''
      }
    }
    Object.keys(previewValues).forEach((key) => delete previewValues[key])
    Object.assign(previewValues, nextValues)
  },
  { immediate: true }
)

const previewDisplayRaw = computed(() => {
  if (previewResult.value && typeof previewResult.value === 'object' && 'raw_text' in previewResult.value) {
    return previewResult.value.raw_text
  }
  if (typeof previewResult.value === 'string') {
    return previewResult.value
  }
  return JSON.stringify(previewResult.value, null, 2)
})

const previewDisplayParsed = computed(() => {
  if (previewResult.value && typeof previewResult.value === 'object' && 'parsed' in previewResult.value) {
    return previewResult.value.parsed
  }
  return previewResult.value
})

const previewDisplayText = computed(() => {
  if (previewResult.value && typeof previewResult.value === 'object') {
    if (typeof previewResult.value.formatted_text === 'string' && previewResult.value.formatted_text.trim()) {
      return previewResult.value.formatted_text
    }
    if (typeof previewResult.value.raw_text === 'string' && previewResult.value.raw_text.trim()) {
      return previewResult.value.raw_text
    }
  }
  if (typeof previewDisplayParsed.value === 'object' && previewDisplayParsed.value !== null) {
    return JSON.stringify(previewDisplayParsed.value, null, 2)
  }
  if (typeof previewDisplayParsed.value === 'string') {
    return previewDisplayParsed.value
  }
  return previewDisplayRaw.value
})

const previewHasRaw = computed(() => {
  return previewDisplayRaw.value && previewDisplayRaw.value !== previewDisplayText.value
})

const tr = (key, fallback) => {
  const translated = t(key)
  return translated === key ? fallback : translated
}

const buildPreviewArguments = () => {
  const payload = {}
  for (const field of previewFields.value) {
    const value = previewValues[field.name]
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

const runPreview = async () => {
  previewLoading.value = true
  previewError.value = ''
  try {
    const argumentsPayload = buildPreviewArguments()
    const response = await toolAPI.execTool({
      tool_name: props.tool.name,
      arguments: argumentsPayload
    })
    previewResult.value = response
  } catch (error) {
    previewError.value = error.message || 'Preview failed'
  } finally {
    previewLoading.value = false
  }
}

// Methods
const getToolTypeLabel = (type) => {
  const typeKey = `tools.type.${type}`
  return t(typeKey) !== typeKey ? t(typeKey) : type
}

const getToolSourceLabel = (source) => {
  let displaySource = source
  if (source.startsWith('MCP Server: ')) {
    displaySource = getMcpServerLabel(source.replace('MCP Server: ', ''), t)
  } else if (source.startsWith('内置MCP: ')) {
    displaySource = getMcpServerLabel(source.replace('内置MCP: ', ''), t)
  }

  const sourceMapping = {
    '基础工具': 'tools.source.basic',
    '内置工具': 'tools.source.builtin',
    '系统工具': 'tools.source.system'
  }

  const translationKey = sourceMapping[displaySource]
  return translationKey ? t(translationKey) : displaySource
}

const getToolIcon = (type) => {
  switch (type) {
    case 'basic':
      return Code
    case 'mcp':
      return Database
    case 'agent':
      return Cpu
    default:
      return Wrench
  }
}

const getToolTypeColorClass = (type) => {
  switch (type) {
    case 'basic':
      return 'bg-blue-500'
    case 'mcp':
      return 'bg-indigo-500'
    case 'agent':
      return 'bg-red-500'
    default:
      return 'bg-green-500'
  }
}

const getToolTypeBadgeVariant = (type) => {
  switch (type) {
    case 'basic':
      return 'default'
    case 'mcp':
      return 'secondary'
    case 'agent':
      return 'destructive'
    default:
      return 'outline'
  }
}

const formatParameters = (parameters, requiredNames = []) => {
  if (!parameters || typeof parameters !== 'object') {
    return []
  }

  const requiredSet = new Set(Array.isArray(requiredNames) ? requiredNames : [])
  return Object.entries(parameters).map(([key, value]) => {
    return {
      name: key,
      type: value.type || 'unknown',
      description: value.description || t('tools.noDescription'),
      required: requiredSet.has(key) || value.required === true
    }
  })
}
</script>
