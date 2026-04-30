<template>
  <div class="tool-call-renderer h-full flex flex-col overflow-hidden">
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
          <div class="flex flex-col overflow-hidden">
            <div class="text-sm font-medium mb-2 flex items-center gap-2">
              <Settings class="w-4 h-4" />
              {{ t('workbench.tool.arguments') }}
            </div>
            <div class="flex-1 overflow-auto bg-muted rounded-lg p-4">
              <pre class="text-xs font-mono whitespace-pre-wrap">{{ formattedArguments }}</pre>
            </div>
          </div>
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

    <div class="flex-1 overflow-hidden">
      <div v-if="!toolArgumentsComplete" class="px-4 py-2 border-b border-amber-500/20 bg-amber-500/5 text-xs text-amber-700 flex items-center gap-2">
        <Loader2 class="w-3.5 h-3.5 animate-spin" />
        <span>{{ t('workbench.tool.argumentsStreaming') }}</span>
      </div>

      <template v-if="isShellCommand">
        <ShellCommandToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
          :live-output="item?.liveOutput || ''"
          :live-segments="item?.liveSegments || []"
          :live="item?.live === true"
        />
      </template>

      <template v-else-if="isLoadSkill">
        <LoadSkillToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <FileReadToolRenderer
        v-else-if="isFileRead"
        :tool-args="toolArgs"
        :tool-result="toolResult"
      />

      <template v-else-if="isFileWrite">
        <FileWriteToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <FileUpdateToolRenderer
        v-else-if="isFileUpdate"
        :tool-args="toolArgs"
        :tool-result="toolResult"
        :formatted-arguments="formattedArguments"
        :display-tool-name="displayToolName"
        :has-arguments="hasArguments"
      />

      <template v-else-if="isTodoWrite">
        <TodoWriteToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isSysSpawnAgent">
        <SysSpawnAgentToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isSysDelegateTask">
        <SysDelegateTaskToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
          :item="item"
        />
      </template>

      <template v-else-if="isSysFinishTask">
        <SysFinishTaskToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isCodeExecution">
        <CodeExecutionToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
          :tool-name="toolName"
        />
      </template>

      <template v-else-if="isSearchWebPage">
        <SearchWebPageToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isSearchImageFromWeb">
        <SearchImageFromWebToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isSearchMemory">
        <MemoryToolRenderer
          :tool-call="item"
          :tool-result="toolResultData"
        />
      </template>

      <template v-else-if="isQuestionnaire">
        <div class="questionnaire-container h-full overflow-auto p-6">
          <QuestionnaireReadonly
            :tool-call="toolCall"
            :tool-result="toolResult"
          />
        </div>
      </template>

      <template v-else-if="isCompressHistory">
        <CompressHistoryToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isGrep">
        <GrepToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isGlob">
        <GlobToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else-if="isListDir">
        <ListDirToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <!-- analyze_image - 图片理解 -->
      <template v-else-if="isAnalyzeImage">
        <ImageUnderstandingToolRenderer
          :tool-args="toolArgs"
          :tool-result="toolResult"
        />
      </template>

      <template v-else>
        <div class="p-4 h-full overflow-auto">
          <div v-if="hasArguments" class="mb-4">
            <div class="text-xs text-muted-foreground mb-2 flex items-center gap-1">
              <Settings class="w-3 h-3" />
              {{ t('workbench.tool.arguments') }}
            </div>
            <pre class="bg-muted p-3 rounded text-xs whitespace-pre-wrap break-all">{{ formattedArguments }}</pre>
          </div>

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

const { t } = useLanguage()

const props = defineProps({
  item: {
    type: Object,
    required: true
  }
})

const showRawDataDialog = ref(false)
const skillInfo = ref({ name: '', description: '', content: '' })
const skillLoading = ref(false)
const skillError = ref('')
const agentList = ref([])
const agentListLoaded = ref(false)
const showDelegationResult = ref(false)

const toolCall = computed(() => props.item.data?.toolCall || props.item.data || {})
const toolResult = computed(() => props.item.toolResult || props.item.data?.toolResult || null)

const toolResultData = computed(() => {
  if (!toolResult.value) return null
  let result = toolResult.value.content
  if (typeof result === 'string') {
    try {
      result = JSON.parse(result)
    } catch {
      return result
    }
  }
  return result
})

const toolName = computed(() => toolCall.value.function?.name || '')

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
  try {
    if (typeof args === 'string') return JSON.parse(args)
    return args || {}
  } catch {
    return {}
  }
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

const isShellCommand = computed(() => toolName.value === 'execute_shell_command')
const isLoadSkill = computed(() => toolName.value === 'load_skill')
const isFileRead = computed(() => toolName.value === 'file_read')
const isFileWrite = computed(() => toolName.value === 'file_write')
const isFileUpdate = computed(() => toolName.value === 'file_update')
const isCodeExecution = computed(() => toolName.value === 'execute_python_code' || toolName.value === 'execute_javascript_code')
const isTodoWrite = computed(() => toolName.value === 'todo_write')
const isSysSpawnAgent = computed(() => toolName.value === 'sys_spawn_agent')
const isSysDelegateTask = computed(() => toolName.value === 'sys_delegate_task')
const isSysFinishTask = computed(() => toolName.value === 'sys_finish_task')
const isSearchWebPage = computed(() => toolName.value === 'search_web_page')
const isSearchImageFromWeb = computed(() => toolName.value === 'search_image_from_web')
const isSearchMemory = computed(() => toolName.value === 'search_memory' || toolName.value === 'memory_search')
const isQuestionnaire = computed(() => toolName.value === 'questionnaire')
const isCompressHistory = computed(() => toolName.value === 'compress_conversation_history')
const isGrep = computed(() => toolName.value === 'grep')
const isGlob = computed(() => toolName.value === 'glob')
const isListDir = computed(() => toolName.value === 'list_dir')
const isAnalyzeImage = computed(() => toolName.value === 'analyze_image')

const displayToolName = computed(() => getToolLabel(toolName.value, t))

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

const skillName = computed(() => toolArgs.value.skill_name || '')

const fetchSkillInfo = async () => {
  if (!isLoadSkill.value || !skillName.value) return
  skillLoading.value = true
  skillError.value = ''
  try {
    const result = await skillAPI.getSkillContent(skillName.value)
    if (result) {
      let name = result.name || skillName.value
      let description = result.description || ''
      let content = result.content || ''
      if (content && !description) {
        const nameMatch = content.match(/^name:\s*(.+)$/m)
        const descMatch = content.match(/^description:\s*(.+)$/m)
        if (nameMatch) {
          name = nameMatch[1].trim()
          content = content.replace(/^name:\s*.+$/m, '').trim()
        }
        if (descMatch) {
          description = descMatch[1].trim()
          content = content.replace(/^description:\s*.+$/m, '').trim()
        }
      }
      skillInfo.value = { name, description, content }
    }
  } catch (error) {
    console.error('[ToolCallRenderer] Failed to fetch skill info:', error)
    skillError.value = t('workbench.tool.loadingSkillError') + ': ' + (error.message || 'Unknown Error')
  } finally {
    skillLoading.value = false
  }
}

watch(isLoadSkill, (newVal) => {
  if (newVal && skillName.value && !skillInfo.value.description) fetchSkillInfo()
}, { immediate: true })

watch(skillName, (newVal, oldVal) => {
  if (newVal !== oldVal) {
    skillInfo.value = { name: '', description: '', content: '' }
    skillError.value = ''
    if (newVal && isLoadSkill.value) fetchSkillInfo()
  }
})

watch(() => props.item?.id, (newId, oldId) => {
  if (newId !== oldId) {
    skillInfo.value = { name: '', description: '', content: '' }
    skillError.value = ''
    agentListLoaded.value = false
    agentList.value = []
  }
})

const executionLanguage = computed(() => {
  if (toolName.value === 'execute_python_code') return 'python'
  if (toolName.value === 'execute_javascript_code') return 'javascript'
  return 'text'
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
  const result = compressHistoryResult.value
  if (!result) return ''
  const match = result.match(/(\d+)\s*tokens?\s*→\s*(\d+)\s*tokens?.*\((压缩率|compression):\s*([^)]+)\)/i)
  if (match) return `${match[1]} → ${match[2]} tokens (${match[4]})`
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

const hasArguments = computed(() => Object.keys(toolArgs.value).length > 0)
const hasResult = computed(() => !!toolResult.value)
const isErrorResult = computed(() => toolResult.value?.is_error)
const errorMessage = computed(() => {
  const content = toolResult.value?.content
  if (typeof content === 'string') return content
  return JSON.stringify(content)
})

const toolResultStatus = computed(() => {
  if (!toolResult.value) return null
  if (toolResult.value.is_error) return { text: t('workbench.tool.statusError'), variant: 'destructive' }
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

const isCodeFile = (type) => ['python', 'javascript', 'typescript', 'vue', 'html', 'css', 'json', 'bash', 'yaml'].includes(type)

const roleLabel = computed(() => {
  const roleMap = {
    assistant: t('workbench.tool.role.ai'),
    user: t('workbench.tool.role.user'),
    system: t('workbench.tool.role.system'),
    tool: t('workbench.tool.role.tool')
  }
  return roleMap[props.item?.role] || t('workbench.tool.role.ai')
})

const roleColor = computed(() => {
  const colorMap = {
    assistant: 'text-primary',
    user: 'text-muted-foreground',
    system: 'text-orange-500',
    tool: 'text-blue-500'
  }
  return colorMap[props.item?.role] || 'text-primary'
})

const formatTime = (timestamp) => {
  if (!timestamp) return ''
  let dateVal = timestamp
  const num = Number(timestamp)
  if (!isNaN(num)) dateVal = num < 10000000000 ? num * 1000 : num
  const date = new Date(dateVal)
  if (isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

const formattedArguments = computed(() => {
  if (!toolArgumentsComplete.value) return toolArgumentsRaw.value || t('workbench.tool.argumentsStreaming')
  return JSON.stringify(toolArgs.value, null, 2)
})
const formattedResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'object') return JSON.stringify(content, null, 2)
  try {
    return JSON.stringify(JSON.parse(content), null, 2)
  } catch {
    return content
  }
})

const todoSummary = computed(() => {
  if (!toolResult.value) return ''
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    return parsed.summary || ''
  } catch {
    return ''
  }
})
const todoTasks = computed(() => {
  if (!toolResult.value) return []
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    return parsed.tasks || []
  } catch {
    return []
  }
})
const getTodoTaskClass = (status) => ({
  completed: 'bg-green-500/10 border-green-500/30',
  pending: 'bg-muted/30 border-border/50',
  in_progress: 'bg-blue-500/10 border-blue-500/30',
  failed: 'bg-red-500/10 border-red-500/30'
}[status] || 'bg-muted/30 border-border/50')
const getTodoStatusVariant = (status) => ({
  completed: 'success',
  pending: 'secondary',
  in_progress: 'default',
  failed: 'destructive'
}[status] || 'secondary')
const getTodoStatusLabel = (status) => ({
  completed: t('workbench.tool.statusCompleted'),
  pending: t('workbench.tool.statusPending'),
  in_progress: t('workbench.tool.statusInProgress'),
  failed: t('workbench.tool.statusFailed')
}[status] || status)

const delegateTasks = computed(() => toolArgs.value.tasks || [])
const generateAvatarUrl = (agentId) => agentId ? `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}` : ''
const getAgentNameById = (agentIdOrName) => {
  if (!agentIdOrName) return t('workbench.tool.unknownAgent')
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  if (!agent) agent = agentList.value.find(a => a.name === agentIdOrName)
  return agent?.name || agentIdOrName
}
const getAgentAvatarUrl = (agentIdOrName) => {
  if (!agentIdOrName) return ''
  let agent = agentList.value.find(a => a.id === agentIdOrName)
  if (!agent) agent = agentList.value.find(a => a.name === agentIdOrName)
  if (agent?.avatar_url) return agent.avatar_url
  return generateAvatarUrl(agentIdOrName)
}
const currentAgentId = computed(() => props.item?.agent_id || props.item?.data?.agent_id || props.item?.data?.source_agent_id || '')
const currentAgentName = computed(() => props.item?.agent_name || props.item?.data?.agent_name || props.item?.data?.source_agent_name || props.item?.role || t('workbench.tool.delegator'))
const currentAgentAvatar = computed(() => getAgentAvatarUrl(currentAgentId.value || currentAgentName.value || 'current'))
const getAgentAvatar = (agentId) => getAgentAvatarUrl(agentId)
const getAgentName = (agentId) => getAgentNameById(agentId)
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
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
})
const delegationResult = computed(() => {
  if (!toolResult.value || toolResult.value.is_error) return null
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content, null, 2)
})

const spawnAgentName = computed(() => toolArgs.value.name || '')
const spawnAgentDescription = computed(() => toolArgs.value.description || '')
const spawnAgentSystemPrompt = computed(() => toolArgs.value.system_prompt || '')
const spawnAgentId = computed(() => {
  if (!toolResult.value) return null
  const message = typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
  const match = message.match(/agent_[a-zA-Z0-9]+/)
  return match ? match[0] : null
})
const spawnAgentError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
})
const spawnAgentAvatarUrl = computed(() => {
  const seed = spawnAgentId.value || spawnAgentName.value || 'default'
  return `https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(seed)}&backgroundColor=b6e3f4,c0aede,d1d4f9`
})
const openSpawnedAgentChat = () => {
  if (!spawnAgentId.value) return
  localStorage.setItem('selectedAgentId', spawnAgentId.value)
  window.location.href = `/chat?agent=${spawnAgentId.value}`
}

const finishTaskStatus = computed(() => toolArgs.value.status || 'success')
const finishTaskResult = computed(() => {
  const resultFromArgs = toolArgs.value.result
  if (resultFromArgs) return typeof resultFromArgs === 'string' ? resultFromArgs : JSON.stringify(resultFromArgs, null, 2)
  if (!toolResult.value) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content, null, 2)
})
const finishTaskError = computed(() => {
  if (!toolResult.value?.is_error) return ''
  return typeof toolResult.value.content === 'string' ? toolResult.value.content : JSON.stringify(toolResult.value.content)
})

const searchQuery = computed(() => toolArgs.value.query || '')
const searchLoading = computed(() => !toolResult.value)
const searchResults = computed(() => {
  if (!toolResult.value) return []
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    if (parsed.results && Array.isArray(parsed.results)) return parsed.results
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
})
const openSearchResult = (url) => {
  if (url) window.open(url, '_blank')
}

const searchImageQuery = computed(() => toolArgs.value.query || '')
const searchImageLoading = computed(() => !toolResult.value)
const searchImageResults = computed(() => {
  if (!toolResult.value) return []
  try {
    const parsed = typeof toolResult.value.content === 'string' ? JSON.parse(toolResult.value.content) : toolResult.value.content
    if (parsed.images && Array.isArray(parsed.images)) return parsed.images
    if (parsed.results && Array.isArray(parsed.results)) return parsed.results
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
})
const openImagePreview = (url) => {
  if (url) window.open(url, '_blank')
}
const handleImageError = (event) => {
  event.target.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"%3E%3Crect width="100" height="100" fill="%23f3f4f6"/%3E%3Ctext x="50" y="50" font-family="Arial" font-size="12" fill="%239ca3af" text-anchor="middle" dy=".3em"%3EImage Error%3C/text%3E%3C/svg%3E'
}

onMounted(() => {
  nextTick(() => {
    if (isSysDelegateTask.value) loadAgentList()
    if (isLoadSkill.value && skillName.value) fetchSkillInfo()
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
