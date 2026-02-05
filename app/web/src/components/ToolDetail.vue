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
          <h1 class="text-xl md:text-2xl font-bold tracking-tight truncate">{{ tool.name }}</h1>
          <Badge :variant="getToolTypeBadgeVariant(tool.type)" class="mt-1">
            {{ getToolTypeLabel(tool.type) }}
          </Badge>
        </div>
      </div>
      <Button variant="outline" @click="$emit('back')" class="w-full sm:w-auto">
        <ArrowLeft class="mr-2 h-4 w-4" />
        {{ t('tools.backToList') }}
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
                <p class="font-medium">{{ tool.name }}</p>
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
      </div>
    </ScrollArea>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowLeft, Database, Code, Wrench, Globe, Cpu } from 'lucide-vue-next'
import { useLanguage } from '../utils/i18n.js'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
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
defineEmits(['back'])

// Composables
const { t } = useLanguage()

// Computed
const formattedParams = computed(() => {
  if (!props.tool || !props.tool.parameters) {
    return []
  }
  return formatParameters(props.tool.parameters)
})

// Methods
const getToolTypeLabel = (type) => {
  const typeKey = `tools.type.${type}`
  return t(typeKey) !== typeKey ? t(typeKey) : type
}

const getToolSourceLabel = (source) => {
  // 直接映射中文source到翻译key
  const sourceMapping = {
    '基础工具': 'tools.source.basic',
    '内置工具': 'tools.source.builtin',
    '系统工具': 'tools.source.system'
  }

  const translationKey = sourceMapping[source]
  return translationKey ? t(translationKey) : source
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

const formatParameters = (parameters) => {
  if (!parameters || typeof parameters !== 'object') {
    return []
  }

  return Object.entries(parameters).map(([key, value]) => {
    return {
      name: key,
      type: value.type || 'unknown',
      description: value.description || t('tools.noDescription'),
      required: value.required || false
    }
  })
}
</script>
