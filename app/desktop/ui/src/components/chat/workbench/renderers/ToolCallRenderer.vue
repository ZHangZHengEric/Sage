<template>
  <div class="tool-call-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="workbench-header flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-muted/30 px-3 py-2.5 flex-none">
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="header-divider text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="header-divider text-muted-foreground/50">|</span>
        <component :is="toolIcon" class="w-4 h-4 text-primary flex-shrink-0" />
        <span class="text-sm font-medium truncate">{{ displayToolName }}</span>
        <Badge v-if="!toolArgumentsComplete" variant="outline" class="text-xs flex-shrink-0 gap-1">
          <Loader2 class="w-3 h-3 animate-spin" />
          {{ t('workbench.tool.argumentsStreaming') }}
        </Badge>
        <Badge v-if="toolResultStatus" :variant="toolResultStatus.variant" class="text-xs flex-shrink-0">
          {{ toolResultStatus.text }}
        </Badge>
      </div>
      <!-- 原始数据按钮 -->
      <Button
        variant="ghost"
        size="sm"
        class="workbench-action-button h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
        @click="showRawDataDialog = true"
      >
        <Code class="w-3 h-3 sm:mr-1" />
        <span class="workbench-action-label">{{ t('workbench.tool.rawData') }}</span>
      </Button>
    </div>

    <!-- 原始数据弹窗 -->
    <Dialog v-model:open="showRawDataDialog">
      <DialogContent class="max-w-4xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2">
            <Code class="w-4 h-4" />
            {{ t('workbench.tool.rawData') }} - {{ displayToolName }}
          </DialogTitle>
          <DialogDescription>
            {{ t('workbench.tool.arguments') }} & {{ t('workbench.tool.result') }}
          </DialogDescription>
        </DialogHeader>
        <div class="grid grid-cols-2 gap-4 flex-1 overflow-hidden">
          <!-- 输入参数 -->
          <div class="flex flex-col overflow-hidden">
            <div class="text-sm font-medium mb-2 flex items-center gap-2">
              <Settings class="w-4 h-4" />
              {{ t('workbench.tool.arguments') }}
            </div>
            <div class="flex-1 overflow-auto bg-muted rounded-lg p-4">
              <pre class="text-xs font-mono whitespace-pre-wrap">{{ formattedArguments }}</pre>
            </div>
          </div>
          <!-- 输出结果 -->
          <div class="flex flex-col overflow-hidden">
            <div class="text-sm font-medium mb-2 flex items-center gap-2">
              <CheckCircle class="w-4 h-4" />
              {{ t('workbench.tool.result') }}
            </div>
            <div class="flex-1 overflow-auto bg-muted rounded-lg p-4">
              <pre class="text-xs font-mono whitespace-pre-wrap">{{ formattedResult }}</pre>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button @click="showRawDataDialog = false">{{ t('workbench.tool.close') }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 工具内容 - 根据工具类型显示不同样式 -->
    <div class="flex-1 overflow-hidden">
      <div v-if="!toolArgumentsComplete" class="px-4 py-2 border-b border-amber-500/20 bg-amber-500/5 text-xs text-amber-700 flex items-center gap-2">
        <Loader2 class="w-3.5 h-3.5 animate-spin" />
        <span>{{ t('workbench.tool.argumentsStreaming') }}</span>
      </div>

      <!-- 1. execute_shell_command - Shell 样式 -->
      <template v-if="isShellCommand">
        <ShellCommandToolRenderer
          :tool-args="toolArgs"
          :arguments-raw="toolArgumentsRaw"
          :tool-result="toolResult"
        />
      </template>

      <!-- 2. load_skill - Skill 描述信息展示 -->
      <template v-else-if="isLoadSkill">
        <LoadSkillToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 3. file_read - 根据文件类型渲染 -->
      <FileReadToolRenderer
        v-else-if="isFileRead"
        :tool-args="toolArgs"
        :tool-result="toolResult"
      />

      <!-- 4. file_write - 根据文件类型渲染 -->
      <template v-else-if="isFileWrite">
        <FileWriteToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 5. file_update - 文件更新摘要 -->
      <FileUpdateToolRenderer
        v-else-if="isFileUpdate"
        :tool-args="toolArgs"
        :tool-result="toolResult"
        :formatted-arguments="formattedArguments"
        :display-tool-name="displayToolName"
        :has-arguments="hasArguments"
      />

      <!-- 6. todo_write - 任务列表渲染 -->
      <template v-else-if="isTodoWrite">
        <TodoWriteToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 6. sys_spawn_agent - Agent 创建结果展示 -->
      <template v-else-if="isSysSpawnAgent">
        <SysSpawnAgentToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 7. sys_delegate_task - 任务委派展示 -->
      <template v-else-if="isSysDelegateTask">
        <SysDelegateTaskToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
          :item="item"
        />
      </template>

      <!-- 8. sys_finish_task - 任务完成结果展示 -->
      <template v-else-if="isSysFinishTask">
        <SysFinishTaskToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 9. execute_python_code / execute_javascript_code - IDE 样式 -->
      <template v-else-if="isCodeExecution">
        <CodeExecutionToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
          :tool-name="toolName"
        />
      </template>

      <!-- 10. search_web_page - 网页搜索结果显示 -->
      <template v-else-if="isSearchWebPage">
        <SearchWebPageToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 11. search_image_from_web - 图片搜索结果显示 -->
      <template v-else-if="isSearchImageFromWeb">
        <SearchImageFromWebToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 12. search_memory - 记忆搜索结果显示 -->
      <template v-else-if="isSearchMemory">
        <MemoryToolRenderer
          :tool-call="item"
          :tool-result="toolResultData"
        />
      </template>

      <!-- 13. questionnaire - 问卷只读预览（工作台不允许提交） -->
      <template v-else-if="isQuestionnaire">
        <div class="questionnaire-container h-full overflow-auto p-6">
          <QuestionnaireReadonly
            :tool-call="toolCall"
            :tool-result="toolResult"
          />
        </div>
      </template>

      <!-- 14. compress_conversation_history - 压缩历史消息展示 -->
      <template v-else-if="isCompressHistory">
        <CompressHistoryToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 15. grep - 结构化代码搜索 -->
      <template v-else-if="isGrep">
        <GrepToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 16. glob - 文件 glob 查找 -->
      <template v-else-if="isGlob">
        <GlobToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 17. list_dir - 目录树展示 -->
      <template v-else-if="isListDir">
        <ListDirToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 18. analyze_image - 图片理解 -->
      <template v-else-if="isAnalyzeImage">
        <ImageUnderstandingToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- 19. 其他工具 - 统一显示 -->
      <template v-else>
        <div class="p-4 h-full overflow-auto">
          <!-- 参数 -->
          <div v-if="hasArguments" class="mb-4">
            <div class="text-xs text-muted-foreground mb-2 flex items-center gap-1">
              <Settings class="w-3 h-3" />
              {{ t('workbench.tool.arguments') }}
            </div>
            <pre class="bg-muted p-3 rounded text-xs whitespace-pre-wrap break-all">{{ formattedArguments }}</pre>
          </div>

          <!-- 结果 -->
          <div v-if="hasResult">
            <div class="text-xs text-muted-foreground mb-2 flex items-center gap-1">
              <CheckCircle class="w-3 h-3" />
              {{ t('workbench.tool.result') }}
            </div>
            <div v-if="isErrorResult" class="bg-destructive/10 text-destructive p-3 rounded text-sm">
              {{ errorMessage }}
            </div>
            <pre v-else class="bg-muted p-3 rounded text-xs whitespace-pre-wrap break-all">{{ formattedResult }}</pre>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import {
  Terminal,
  FileText,
  Search,
  Code,
  Database,
  Globe,
  Settings,
  Zap,
  CheckCircle,
  ListTodo,
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
  HelpCircle,
  MessageSquare,
  ArrowRight,
  User,
  Eye,
  EyeOff,
  Image as ImageIcon,
  Brain,
  Bot,
  Minimize2
} from 'lucide-vue-next'
import SyntaxHighlighter from '../../SyntaxHighlighter.vue'
import MarkdownRenderer from '../../MarkdownRenderer.vue'
import { MemoryToolRenderer } from './toolcall'
import FileReadToolRenderer from './toolcall/FileReadToolRenderer.vue'
import FileWriteToolRenderer from './toolcall/FileWriteToolRenderer.vue'
import FileUpdateToolRenderer from './toolcall/FileUpdateToolRenderer.vue'
import QuestionnaireReadonly from './toolcall/QuestionnaireReadonly.vue'
import ShellCommandToolRenderer from './toolcall/ShellCommandToolRenderer.vue'
import LoadSkillToolRenderer from './toolcall/LoadSkillToolRenderer.vue'
import TodoWriteToolRenderer from './toolcall/TodoWriteToolRenderer.vue'
import SysSpawnAgentToolRenderer from './toolcall/SysSpawnAgentToolRenderer.vue'
import SysDelegateTaskToolRenderer from './toolcall/SysDelegateTaskToolRenderer.vue'
import SysFinishTaskToolRenderer from './toolcall/SysFinishTaskToolRenderer.vue'
import CodeExecutionToolRenderer from './toolcall/CodeExecutionToolRenderer.vue'
import SearchWebPageToolRenderer from './toolcall/SearchWebPageToolRenderer.vue'
import SearchImageFromWebToolRenderer from './toolcall/SearchImageFromWebToolRenderer.vue'
import CompressHistoryToolRenderer from './toolcall/CompressHistoryToolRenderer.vue'
import GrepToolRenderer from './toolcall/GrepToolRenderer.vue'
import GlobToolRenderer from './toolcall/GlobToolRenderer.vue'
import ListDirToolRenderer from './toolcall/ListDirToolRenderer.vue'
import ImageUnderstandingToolRenderer from './toolcall/ImageUnderstandingToolRenderer.vue'
import { skillAPI } from '@/api/skill.js'
import { agentAPI } from '@/api/agent.js'
import { useLanguage } from '@/utils/i18n'
import { getToolLabel } from '@/utils/messageLabels.js'
import { parseTodoWriteToolCallArguments } from '@/utils/parseTodoWriteToolArguments.js'
import {
  parseToolJsonValue,
  stringifyToolContentPretty,
  parseToolJsonObjectRecord
} from '@/utils/safeParseToolJson.js'

const { t } = useLanguage()

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

// 显示原始数据弹窗
const showRawDataDialog = ref(false)

// Skill 信息缓存
const skillInfo = ref({
  name: '',
  description: '',
  content: ''
})
const skillLoading = ref(false)
const skillError = ref('')

// Agent 列表缓存
const agentList = ref([])
const agentListLoaded = ref(false)

// 从 item 中提取工具调用信息
const toolCall = computed(() => {
  return props.item.data?.toolCall || props.item.data || {}
})

const toolResult = computed(() => {
  return props.item.toolResult || props.item.data?.toolResult || null
})

// 提取工具结果数据（用于传递给子组件）
const toolResultData = computed(() => {
  if (!toolResult.value) return null
  const parsed = parseToolJsonValue(toolResult.value.content)
  if (parsed !== null) return parsed
  const result = toolResult.value.content
  if (typeof result === 'string') return result
  return result
})

const toolName = computed(() => {
  return toolCall.value.function?.name || ''
})

// 监听 toolResult 变化，用于调试实时数据同步问题
watch(() => props.item.toolResult, (newVal, oldVal) => {
  console.log('[ToolCallRenderer] toolResult changed:', {
    toolName: toolName.value,
    hasNewVal: !!newVal,
    hasOldVal: !!oldVal,
    newValKeys: newVal ? Object.keys(newVal) : [],
    content: newVal?.content
  })
})

const toolArgs = computed(() => {
  const args = toolCall.value.function?.arguments
  if (typeof args === 'object' && args !== null && !Array.isArray(args)) return args
  if (typeof args === 'string') {
    try {
      return JSON.parse(args)
    } catch {
      if (toolName.value === 'todo_write') {
        const { tasks } = parseTodoWriteToolCallArguments(args)
        if (Array.isArray(tasks) && tasks.length > 0) return { tasks }
      }
      return {}
    }
  }
  return {}
})

const toolArgumentsRaw = computed(() => {
  const args = toolCall.value.function?.arguments
  if (typeof args === 'string') return args
  if (args && typeof args === 'object') {
    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return ''
    }
  }
  return ''
})

const toolArgumentsComplete = computed(() => {
  if (toolResult.value) return true
  const args = toolCall.value.function?.arguments
  if (args === null || args === undefined || args === '') return false
  if (typeof args === 'string') {
    try {
      JSON.parse(args)
      return true
    } catch {
      return false
    }
  }
  return true
})

// 工具类型判断
const isShellCommand = computed(() => toolName.value === 'execute_shell_command')
const isLoadSkill = computed(() => toolName.value === 'load_skill')
const isFileRead = computed(() => toolName.value === 'file_read')
const isFileWrite = computed(() => toolName.value === 'file_write')
const isFileUpdate = computed(() => toolName.value === 'file_update')
const isCodeExecution = computed(() =>
  toolName.value === 'execute_python_code' ||
  toolName.value === 'execute_javascript_code'
)
const isTodoWrite = computed(() => toolName.value === 'todo_write')
const isSysSpawnAgent = computed(() => toolName.value === 'sys_spawn_agent')
const isSysDelegateTask = computed(() => toolName.value === 'sys_delegate_task')
const isSysFinishTask = computed(() => toolName.value === 'sys_finish_task')
const isSearchWebPage = computed(() => toolName.value === 'search_web_page')
const isSearchImageFromWeb = computed(() => toolName.value === 'search_image_from_web')
const isSearchMemory = computed(() => toolName.value === 'search_memory')
const isQuestionnaire = computed(() => toolName.value === 'questionnaire')
const isCompressHistory = computed(() => toolName.value === 'compress_conversation_history')
const isGrep = computed(() => toolName.value === 'grep')
const isGlob = computed(() => toolName.value === 'glob')
const isListDir = computed(() => toolName.value === 'list_dir')
const isAnalyzeImage = computed(() => toolName.value === 'analyze_image')

// 显示名称映射
const displayToolName = computed(() => {
  return getToolLabel(toolName.value, t)
})

// ============ 1. Shell 命令 ============
const shellCommand = computed(() => toolArgs.value.command || '')
const shellOutput = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.stdout || parsed.output || content
    } catch {
      return content
    }
  }
  return content?.stdout || content?.output || JSON.stringify(content)
})
const shellError = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content)
      return parsed.stderr || parsed.error
    } catch {
      return ''
    }
  }
  return content?.stderr || content?.error
})

// ============ 2. Load Skill ============
const skillName = computed(() => toolArgs.value.skill_name || '')
const skillDescription = computed(() => {
  const content = toolResult.value?.content
  if (!content) return ''
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.description || ''
  } catch {
    return ''
  }
})
const skillContent = computed(() => {
  const content = toolResult.value?.content
  if (!content) return ''
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.content || parsed.markdown || JSON.stringify(parsed, null, 2)
  } catch {
    return typeof content === 'string' ? content : JSON.stringify(content, null, 2)
  }
})

// 获取 Skill 详细信息
const fetchSkillInfo = async () => {
  console.log('[ToolCallRenderer] fetchSkillInfo called, isLoadSkill:', isLoadSkill.value, 'skillName:', skillName.value)
  if (!isLoadSkill.value || !skillName.value) {
    console.log('[ToolCallRenderer] Skipping fetchSkillInfo')
    return
  }

  skillLoading.value = true
  skillError.value = ''

  try {
    console.log('[ToolCallRenderer] Fetching skill info for:', skillName.value)
    const result = await skillAPI.getSkillContent(skillName.value)
    console.log('[ToolCallRenderer] Skill API result:', result)
    if (result) {
      // 解析 skill 内容
      let name = result.name || skillName.value
      let description = result.description || ''
      let content = result.content || ''

      // 如果 content 是 Markdown 格式，尝试从中提取 name 和 description
      if (content && !description) {
        const nameMatch = content.match(/^name:\s*(.+)$/m)
        const descMatch = content.match(/^description:\s*(.+)$/m)
        if (nameMatch) {
          name = nameMatch[1].trim()
          // 删除 content 中的 name 行
          content = content.replace(/^name:\s*.+$/m, '').trim()
        }
        if (descMatch) {
          description = descMatch[1].trim()
          // 删除 content 中的 description 行
          content = content.replace(/^description:\s*.+$/m, '').trim()
        }
      }

      skillInfo.value = {
        name: name,
        description: description,
        content: content
      }
      console.log('[ToolCallRenderer] skillInfo updated:', skillInfo.value)
    } else {
      console.log('[ToolCallRenderer] Skill API returned no result')
    }
  } catch (error) {
    console.error('[ToolCallRenderer] Failed to fetch skill info:', error)
    skillError.value = t('workbench.tool.loadingSkillError') + ': ' + (error.message || 'Unknown Error')
  } finally {
    skillLoading.value = false
    console.log('[ToolCallRenderer] fetchSkillInfo completed, skillLoading:', skillLoading.value)
  }
}

// 如果是 load_skill，获取 skill 信息
watch(isLoadSkill, (newVal) => {
  console.log('[ToolCallRenderer] isLoadSkill changed:', newVal, 'skillName:', skillName.value)
  if (newVal && skillName.value && !skillInfo.value.description) {
    console.log('[ToolCallRenderer] Calling fetchSkillInfo from watch')
    fetchSkillInfo()
  }
}, { immediate: true })



// 监听 skillName 变化，重置 skillInfo
watch(skillName, (newVal, oldVal) => {
  console.log('[ToolCallRenderer] skillName changed:', oldVal, '->', newVal)
  if (newVal !== oldVal) {
    // 重置 skillInfo
    skillInfo.value = {
      name: '',
      description: '',
      content: ''
    }
    skillError.value = ''
    console.log('[ToolCallRenderer] skillInfo reset for new skill:', newVal)
    // 如果新的 skillName 不为空，获取新 skill 的信息
    if (newVal && isLoadSkill.value) {
      fetchSkillInfo()
    }
  }
})

// 监听 item 变化，确保组件复用时重置状态
watch(() => props.item?.id, (newId, oldId) => {
  if (newId !== oldId) {
    // 重置 skillInfo
    skillInfo.value = { name: '', description: '', content: '' }
    skillError.value = ''
    // 重置 agentList 加载状态
    agentListLoaded.value = false
    agentList.value = []
  }
})

// ============ 4. Code Execution ============
const executionLanguage = computed(() => {
  if (toolName.value === 'execute_python_code') return 'python'
  if (toolName.value === 'execute_javascript_code') return 'javascript'
  return 'text'
})

// ============ 5.5 Compress History ============
const compressHistoryResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  try {
    const parsed = JSON.parse(content)
    return parsed.message || parsed.content || content
  } catch {
    return content
  }
})
const compressHistoryStats = computed(() => {
  // 尝试从结果中提取压缩统计信息
  const result = compressHistoryResult.value
  if (!result) return ''
  // 匹配 "X tokens → Y tokens (压缩率: Z%)" 格式
  const match = result.match(/(\d+)\s*tokens?\s*→\s*(\d+)\s*tokens?.*\((压缩率|compression):\s*([^)]+)\)/i)
  if (match) {
    return `${match[1]} → ${match[2]} tokens (${match[4]})`
  }
  return ''
})
const compressHistoryError = computed(() => {
  if (!toolResult.value?.content) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  try {
    const parsed = JSON.parse(content)
    return parsed.message || parsed.error || t('workbench.tool.unknownError')
  } catch {
    return String(content)
  }
})
const executedCode = computed(() => toolArgs.value.code || '')
const executionResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.result || parsed.output || parsed.stdout || content
  } catch {
    return content
  }
})
const executionError = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.error || parsed.stderr
  } catch {
    return toolResult.value.is_error ? content : ''
  }
})

// ============ 6. 其他工具 ============
const hasArguments = computed(() => {
  const raw = toolArgumentsRaw.value
  if (raw && String(raw).trim()) return true
  return Object.keys(toolArgs.value).length > 0
})
const hasResult = computed(() => !!toolResult.value)
const isErrorResult = computed(() => toolResult.value?.is_error)
const errorMessage = computed(() => {
  const content = toolResult.value?.content
  if (typeof content === 'string') return content
  return JSON.stringify(content)
})

// ============ 通用 ============
const toolResultStatus = computed(() => {
  if (!toolResult.value) return null
  if (toolResult.value.is_error) {
    return { text: t('workbench.tool.statusError'), variant: 'destructive' }
  }
  return { text: t('workbench.tool.statusCompleted'), variant: 'outline' }
})

const toolIcon = computed(() => {
  const name = toolName.value.toLowerCase()
  if (name.includes('terminal') || name.includes('command') || name.includes('shell')) return Terminal
  if (name.includes('file') || name.includes('read') || name.includes('write')) return FileText
  if (name === 'search_memory' || name.includes('memory')) return Brain
  if (name.includes('search')) return Search
  if (name.includes('code') || name.includes('python') || name.includes('javascript')) return Code
  if (name.includes('db') || name.includes('sql') || name.includes('query')) return Database
  if (name.includes('web') || name.includes('http') || name.includes('url')) return Globe
  if (name.includes('skill')) return Settings
  if (name.includes('compress')) return Minimize2
  return Zap
})

const isCodeFile = (type) => {
  const codeTypes = ['python', 'javascript', 'typescript', 'vue', 'html', 'css', 'json', 'bash', 'yaml']
  return codeTypes.includes(type)
}

// ItemHeader 相关信息
const roleLabel = computed(() => {
  const roleMap = {
    'assistant': t('workbench.tool.role.ai'),
    'user': t('workbench.tool.role.user'),
    'system': t('workbench.tool.role.system'),
    'tool': t('workbench.tool.role.tool')
  }
  return roleMap[props.item?.role] || t('workbench.tool.role.ai')
})

const roleColor = computed(() => {
  const colorMap = {
    'assistant': 'text-primary',
    'user': 'text-muted-foreground',
    'system': 'text-orange-500',
    'tool': 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  let dateVal = timestamp
  const num = Number(timestamp)
  if (!isNaN(num)) {
    dateVal = num < 10000000000 ? num * 1000 : num
  }
  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

const formattedArguments = computed(() => {
  const raw = toolArgumentsRaw.value
  if (!toolArgumentsComplete.value) return raw || t('workbench.tool.argumentsStreaming')
  const args = toolCall.value.function?.arguments
  if (typeof args === 'string') {
    try {
      return JSON.stringify(JSON.parse(args), null, 2)
    } catch {
      return String(raw).trim() ? raw : '{}'
    }
  }
  if (args && typeof args === 'object') {
    try {
      return JSON.stringify(args, null, 2)
    } catch {
      return raw || '{}'
    }
  }
  return '{}'
})

const formattedResult = computed(() => {
  if (!toolResult.value) return ''
  return stringifyToolContentPretty(toolResult.value.content)
})

// ============ 7. Todo Write ============
const todoSummary = computed(() => {
  if (!toolResult.value) return ''
  const o = parseToolJsonObjectRecord(toolResult.value.content)
  return o.summary || ''
})

const todoTasks = computed(() => {
  if (!toolResult.value) return []
  const o = parseToolJsonObjectRecord(toolResult.value.content)
  return Array.isArray(o.tasks) ? o.tasks : []
})

const getTodoTaskClass = (status) => {
  const classMap = {
    'completed': 'bg-green-500/10 border-green-500/30',
    'pending': 'bg-muted/30 border-border/50',
    'in_progress': 'bg-blue-500/10 border-blue-500/30',
    'failed': 'bg-red-500/10 border-red-500/30'
  }
  return classMap[status] || 'bg-muted/30 border-border/50'
}

const getTodoStatusVariant = (status) => {
  const variantMap = {
    'completed': 'success',
    'pending': 'secondary',
    'in_progress': 'default',
    'failed': 'destructive'
  }
  return variantMap[status] || 'secondary'
}

const getTodoStatusLabel = (status) => {
  const labelMap = {
    'completed': t('workbench.tool.statusCompleted'),
    'pending': t('workbench.tool.statusPending'),
    'in_progress': t('workbench.tool.statusInProgress'),
    'failed': t('workbench.tool.statusFailed')
  }
  return labelMap[status] || status
}

// ============ 8. Sys Delegate Task ============
const delegateTasks = computed(() => toolArgs.value.tasks || [])
const showDelegationResult = ref(false)

// 统一的 avatar 生成函数
const generateAvatarUrl = (agentId) => {
  if (!agentId) return ''
  return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}`
}

// 获取 agent 名称
const getAgentNameById = (agentIdOrName) => {
  if (!agentIdOrName) return t('workbench.tool.unknownAgent')
  // 先通过 ID 查找
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  // 如果没找到，通过 name 查找
  if (!agent) {
    agent = agentList.value.find(a => a.name === agentIdOrName)
  }
  return agent?.name || agentIdOrName
}

// 获取 agent 头像 URL
const getAgentAvatarUrl = (agentIdOrName) => {
  if (!agentIdOrName) return ''
  // 先通过 ID 查找
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  // 如果没找到，通过 name 查找
  if (!agent) {
    agent = agentList.value.find(a => a.name === agentIdOrName)
  }
  if (agent?.avatar_url) {
    return agent.avatar_url
  }
  // 使用传入的 ID 或 name 作为 seed 生成头像
  return generateAvatarUrl(agentIdOrName)
}

// Get current agent info from item
const currentAgentId = computed(() => {
  // Try to get agent_id from various possible locations
  return props.item?.agent_id ||
         props.item?.data?.agent_id ||
         props.item?.data?.source_agent_id ||
         ''
})

const currentAgentName = computed(() => {
  // Try to get from various possible locations
  return props.item?.agent_name ||
         props.item?.data?.agent_name ||
         props.item?.data?.source_agent_name ||
         props.item?.role || // 如果都没有，使用 role
         t('workbench.tool.delegator')
})

const currentAgentAvatar = computed(() => {
  const agentId = currentAgentId.value
  const agentName = currentAgentName.value
  // 使用 agentId 或 agentName 作为 seed，与 SysDelegateTaskMessage.vue 保持一致
  const seed = agentId || agentName || 'current'
  return getAgentAvatarUrl(seed)
})

const getAgentAvatar = (agentId) => {
  return getAgentAvatarUrl(agentId)
}

const getAgentName = (agentId) => {
  return getAgentNameById(agentId)
}

// 加载 agent 列表
const loadAgentList = async () => {
  if (agentListLoaded.value) return
  try {
    const agents = await agentAPI.getAgents()
    agentList.value = agents || []
    agentListLoaded.value = true
  } catch (error) {
    console.error('[ToolCallRenderer] Failed to load agent list:', error)
  }
}

const delegationError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  return JSON.stringify(content)
})

const delegationResult = computed(() => {
  if (!toolResult.value || toolResult.value.is_error) return null
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  return JSON.stringify(content, null, 2)
})

// ============ 9. Sys Spawn Agent ============
const spawnAgentName = computed(() => toolArgs.value.name || '')
const spawnAgentDescription = computed(() => toolArgs.value.description || '')
const spawnAgentSystemPrompt = computed(() => toolArgs.value.system_prompt || '')

// Extract agent ID from result message
const spawnAgentId = computed(() => {
  if (!toolResult.value) return null
  const message = typeof toolResult.value.content === 'string'
    ? toolResult.value.content
    : JSON.stringify(toolResult.value.content)
  // Match pattern like "agent_360ab10e" from "Agent spawned successfully. ID: agent_360ab10e."
  const match = message.match(/agent_[a-f0-9]+/)
  return match ? match[0] : null
})

const spawnAgentError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  return JSON.stringify(content)
})

// Generate avatar URL using dicebear API
const spawnAgentAvatarUrl = computed(() => {
  const seed = spawnAgentId.value || spawnAgentName.value || 'default'
  return `https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(seed)}&backgroundColor=b6e3f4,c0aede,d1d4f9`
})

const openSpawnedAgentChat = () => {
  if (!spawnAgentId.value) return
  // 先更新 localStorage，确保跳转后能被正确选中
  localStorage.setItem('selectedAgentId', spawnAgentId.value)
  console.log('[ToolCallRenderer] Saved agent to localStorage:', spawnAgentId.value)
  // 使用 window.location.href 强制刷新页面，确保 onMounted 执行
  window.location.href = `/chat?agent=${spawnAgentId.value}`
}

// ============ 10. Sys Finish Task ============
const finishTaskStatus = computed(() => {
  return toolArgs.value.status || 'success'
})

const finishTaskResult = computed(() => {
  // 优先从参数中获取 result
  const resultFromArgs = toolArgs.value.result
  if (resultFromArgs) {
    return typeof resultFromArgs === 'string' ? resultFromArgs : JSON.stringify(resultFromArgs, null, 2)
  }
  // 否则从结果中获取
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  return JSON.stringify(content, null, 2)
})

const finishTaskError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  const content = toolResult.value.content
  if (typeof content === 'string') return content
  return JSON.stringify(content)
})

// ============ 11. Search Web Page ============
const searchQuery = computed(() => toolArgs.value.query || '')
const searchLoading = computed(() => !toolResult.value)
const searchResults = computed(() => {
  if (!toolResult.value) return []
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    if (parsed.results && Array.isArray(parsed.results)) {
      return parsed.results
    }
    if (Array.isArray(parsed)) {
      return parsed
    }
    return []
  } catch {
    return []
  }
})

const openSearchResult = (url) => {
  if (url) {
    window.open(url, '_blank')
  }
}

// ============ 12. Search Image From Web ============
const searchImageQuery = computed(() => toolArgs.value.query || '')
const searchImageLoading = computed(() => !toolResult.value)
const searchImageResults = computed(() => {
  if (!toolResult.value) return []
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    if (parsed.images && Array.isArray(parsed.images)) {
      return parsed.images
    }
    if (parsed.results && Array.isArray(parsed.results)) {
      return parsed.results
    }
    if (Array.isArray(parsed)) {
      return parsed
    }
    return []
  } catch {
    return []
  }
})

const openImagePreview = (url) => {
  if (url) {
    window.open(url, '_blank')
  }
}

const handleImageError = (event, index) => {
  // 图片加载失败时显示占位符
  event.target.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"%3E%3Crect width="100" height="100" fill="%23f3f4f6"/%3E%3Ctext x="50" y="50" font-family="Arial" font-size="12" fill="%239ca3af" text-anchor="middle" dy=".3em"%3EImage Error%3C/text%3E%3C/svg%3E'
}

// 组件挂载时加载需要的数据
onMounted(() => {
  // 使用 nextTick 确保 DOM 已更新
  nextTick(() => {
    if (isSysDelegateTask.value) {
      loadAgentList()
    }
    if (isLoadSkill.value && skillName.value) {
      fetchSkillInfo()
    }
  })
})

</script>

<style scoped>
.shell-container {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}

@media (max-width: 520px) {
  .workbench-action-label,
  .header-divider {
    display: none;
  }

  .workbench-action-button {
    padding-left: 0.5rem;
    padding-right: 0.5rem;
  }
}

.shell-header {
  border-bottom: 1px solid #333;
  padding-bottom: 8px;
}

.ide-container {
  display: flex;
  flex-direction: column;
}

.code-section,
.result-section {
  flex: 1;
  overflow: hidden;
}

.section-header {
  border-bottom: 1px solid hsl(var(--border));
}
</style>
