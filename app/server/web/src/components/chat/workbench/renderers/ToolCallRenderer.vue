<template>
  <div class="tool-call-renderer h-full flex flex-col overflow-hidden">
    <!-- 整合头部 -->
    <div class="flex items-center justify-between px-3 py-2.5 bg-muted/30 border-b border-border flex-none h-12">
      <div class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm" :class="roleColor">{{ roleLabel }}</span>
        <span class="text-muted-foreground/50">|</span>
        <span class="text-sm text-muted-foreground">{{ formatTime(item?.timestamp) }}</span>
        <span class="text-muted-foreground/50">|</span>
        <component :is="toolIcon" class="w-4 h-4 text-primary flex-shrink-0" />
        <span class="text-sm font-medium truncate">{{ displayToolName }}</span>
        <Badge v-if="toolResultStatus" :variant="toolResultStatus.variant" class="text-xs flex-shrink-0">
          {{ toolResultStatus.text }}
        </Badge>
      </div>
      <!-- 原始数据按钮 -->
      <Button
        variant="ghost"
        size="sm"
        class="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
        @click="showRawDataDialog = true"
      >
        <Code class="w-3 h-3 mr-1" />
        {{ t('workbench.tool.rawData') }}
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
      <!-- 1. execute_shell_command - Shell 样式 -->
      <template v-if="isShellCommand">
        <div class="shell-container bg-black text-green-400 font-mono text-sm p-4 h-full overflow-auto">
          <div class="shell-header text-gray-500 mb-2">$ {{ shellCommand }}</div>
          <div v-if="shellOutput" class="shell-output whitespace-pre-wrap break-all">{{ shellOutput }}</div>
          <div v-if="shellError" class="shell-error text-red-400 mt-2 whitespace-pre-wrap break-all">{{ shellError }}</div>
        </div>
      </template>

      <!-- 2. load_skill - Skill 描述信息展示 -->
      <template v-else-if="isLoadSkill">
        <div class="skill-content h-full overflow-auto p-6">
          <!-- 加载中状态 -->
          <div v-if="skillLoading" class="flex items-center justify-center h-full text-muted-foreground">
            <div class="animate-spin mr-2">
              <Settings class="w-5 h-5" />
            </div>
            {{ t('workbench.tool.loadingSkill') }}
          </div>
          <!-- 错误状态 -->
          <div v-else-if="skillError" class="text-red-500">
            {{ skillError }}
          </div>
          <!-- Skill 信息 -->
          <div v-else-if="skillInfo.description">
            <div class="text-lg font-semibold mb-4">{{ skillInfo.name }}</div>
            <div class="text-sm text-muted-foreground mb-6">{{ skillInfo.description }}</div>
            <div v-if="skillInfo.content" class="skill-markdown">
              <MarkdownRenderer :content="skillInfo.content" />
            </div>
          </div>
          <!-- 备用显示 -->
          <div v-else>
            <div class="text-sm text-muted-foreground">{{ t('workbench.tool.loadingSkillWait', { name: skillName }) }}</div>
          </div>
        </div>
      </template>

      <!-- 3. file_read - 根据文件类型渲染 -->
      <FileReadToolRenderer
        v-else-if="isFileRead"
        :tool-args="toolArgs"
        :tool-result="toolResult"
      />

      <!-- 4. file_write - 根据文件类型渲染 -->
      <template v-else-if="isFileWrite">
        <div class="h-full flex flex-col">
          <div class="file-header px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
            <FileText class="w-4 h-4" />
            <span class="font-medium text-sm">{{ writeFilePath }}</span>
            <Badge variant="secondary" class="text-xs">{{ writeFileType }}</Badge>
          </div>
          <div class="write-info px-4 py-2 text-sm text-muted-foreground flex-none border-b border-border">
            {{ t('workbench.tool.writtenBytes', { bytes: writeContentLength }) }}
          </div>
          <div class="file-content flex-1 overflow-auto p-4">
            <SyntaxHighlighter
              v-if="isCodeFile(writeFileType)"
              :code="writeContent"
              :language="writeFileType"
            />
            <MarkdownRenderer
              v-else-if="writeFileType === 'markdown'"
              :content="writeContent"
            />
            <pre v-else class="whitespace-pre-wrap text-sm">{{ writeContent }}</pre>
          </div>
        </div>
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
        <div class="todo-write-container h-full overflow-auto p-4">
          <!-- 摘要信息 -->
          <div v-if="todoSummary" class="mb-4 p-3 bg-muted/30 rounded-lg border border-border/50">
            <div class="flex items-center gap-2 text-sm">
              <ListTodo class="w-4 h-4 text-primary" />
              <span>{{ todoSummary }}</span>
            </div>
          </div>
          <!-- 任务列表 -->
          <div v-if="todoTasks.length > 0" class="space-y-2">
            <div
              v-for="task in todoTasks"
              :key="task.id"
              class="flex items-center gap-3 p-3 rounded-lg border transition-colors"
              :class="getTodoTaskClass(task.status)"
            >
              <!-- 状态图标 -->
              <div class="flex-shrink-0">
                <CheckCircle2 v-if="task.status === 'completed'" class="w-5 h-5 text-green-500" />
                <Circle v-else-if="task.status === 'pending'" class="w-5 h-5 text-muted-foreground" />
                <Loader2 v-else-if="task.status === 'in_progress'" class="w-5 h-5 text-blue-500 animate-spin" />
                <XCircle v-else-if="task.status === 'failed'" class="w-5 h-5 text-red-500" />
                <HelpCircle v-else class="w-5 h-5 text-muted-foreground" />
              </div>
              <!-- 任务信息 -->
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-xs text-muted-foreground font-mono">#{{ task.index }}</span>
                  <span class="text-sm font-medium truncate">{{ task.name }}</span>
                </div>
                <div class="text-xs text-muted-foreground/70 mt-0.5">{{ task.id }}</div>
              </div>
              <!-- 状态标签 -->
              <Badge
                :variant="getTodoStatusVariant(task.status)"
                class="text-xs flex-shrink-0"
              >
                {{ getTodoStatusLabel(task.status) }}
              </Badge>
            </div>
          </div>
          <!-- 无任务提示 -->
          <div v-else class="flex items-center justify-center h-32 text-muted-foreground">
            <div class="text-center">
              <ListTodo class="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p class="text-sm">暂无任务</p>
            </div>
          </div>
        </div>
      </template>

      <!-- 7. execute_python_code / execute_javascript_code - IDE 样式 -->
      <template v-else-if="isCodeExecution">
        <div class="ide-container h-full flex flex-col bg-[#1e1e1e] overflow-hidden">
          <!-- 代码区域 - 占主要空间，直接显示高亮代码 -->
          <div class="code-section flex-[3] min-h-0 overflow-auto">
            <SyntaxHighlighter 
              :code="executedCode" 
              :language="executionLanguage" 
              :show-header="false"
              :show-copy-button="false"
              class="h-full !my-0 !rounded-none !border-0"
            />
          </div>
          <!-- 结果区域 - 更小，紧凑显示 -->
          <div v-if="executionResult" class="result-section flex-1 min-h-[80px] max-h-[150px] flex flex-col border-t border-border/30 bg-black/20 overflow-hidden">
            <div class="section-header px-3 py-1.5 bg-muted/30 text-[10px] text-muted-foreground flex items-center gap-1.5 flex-none">
              <Terminal class="w-3 h-3" />
              {{ t('workbench.tool.result') }}
            </div>
            <div class="result-content flex-1 overflow-auto px-3 py-2 font-mono text-xs">
              <div v-if="executionError" class="text-red-400">{{ executionError }}</div>
              <pre v-else class="whitespace-pre-wrap text-gray-300">{{ executionResult }}</pre>
            </div>
          </div>
        </div>
      </template>

      <!-- 8. questionnaire - 问卷表单 -->
      <template v-else-if="isQuestionnaire">
        <div class="questionnaire-container h-full overflow-auto p-4">
          <QuestionnaireForm
            :questionnaire-id="questionnaireId"
            :title="questionnaireTitle"
            :questions="questionnaireQuestions"
            :wait-time="questionnaireWaitTime"
            @submit="handleQuestionnaireSubmit"
          />
        </div>
      </template>

      <!-- 9. 其他工具 - 统一显示 -->
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
import { ref, computed, watch } from 'vue'
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
  HelpCircle
} from 'lucide-vue-next'
import SyntaxHighlighter from '../../SyntaxHighlighter.vue'
import MarkdownRenderer from '../../MarkdownRenderer.vue'
import QuestionnaireForm from '../../tools/QuestionnaireForm.vue'
import FileReadToolRenderer from './toolcall/FileReadToolRenderer.vue'
import FileUpdateToolRenderer from './toolcall/FileUpdateToolRenderer.vue'
import { skillAPI } from '@/api/skill.js'
import { useLanguage } from '@/utils/i18n'
import { getToolLabel } from '@/utils/messageLabels.js'

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

// 从 item 中提取工具调用信息
const toolCall = computed(() => {
  return props.item.data?.toolCall || props.item.data || {}
})

const toolResult = computed(() => {
  return props.item.toolResult || props.item.data?.toolResult || null
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
  try {
    const args = toolCall.value.function?.arguments
    if (typeof args === 'string') {
      return JSON.parse(args)
    }
    return args || {}
  } catch {
    return {}
  }
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
const isQuestionnaire = computed(() => toolName.value === 'questionnaire')

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
watch(() => props.item, (newVal, oldVal) => {
  console.log('[ToolCallRenderer] item changed:', oldVal?.id, '->', newVal?.id)
  if (newVal?.id !== oldVal?.id) {
    // 重置 skillInfo
    skillInfo.value = {
      name: '',
      description: '',
      content: ''
    }
    skillError.value = ''
    console.log('[ToolCallRenderer] item changed, skillInfo reset')
    // 如果是 load_skill，获取新 skill 的信息
    if (isLoadSkill.value && skillName.value) {
      fetchSkillInfo()
    }
  }
}, { deep: true })

// ============ 4. File Write ============
const writeFilePath = computed(() => toolArgs.value.file_path || '')
const writeFileType = computed(() => {
  const path = writeFilePath.value
  const ext = path.split('.').pop()?.toLowerCase()
  const typeMap = {
    'py': 'python',
    'js': 'javascript',
    'ts': 'typescript',
    'vue': 'vue',
    'html': 'html',
    'css': 'css',
    'json': 'json',
    'md': 'markdown',
    'txt': 'text',
    'yml': 'yaml',
    'yaml': 'yaml',
    'sh': 'bash'
  }
  return typeMap[ext] || ext || 'text'
})
const writeContent = computed(() => toolArgs.value.content || '')
const writeContentLength = computed(() => {
  const content = writeContent.value
  return content ? new Blob([content]).size : 0
})

// ============ 5. Code Execution ============
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

// ============ 6. Questionnaire ============
const questionnaireId = computed(() => {
  return toolArgs.value.questionnaire_id || ''
})

const questionnaireTitle = computed(() => {
  return toolArgs.value.title || '问卷'
})

const questionnaireQuestions = computed(() => {
  return toolArgs.value.questions || []
})

const questionnaireWaitTime = computed(() => {
  return toolArgs.value.wait_time || 300
})

const handleQuestionnaireSubmit = (result) => {
  console.log('[ToolCallRenderer] Questionnaire submitted:', result)
}

// ============ 7. 其他工具 ============
const hasArguments = computed(() => Object.keys(toolArgs.value).length > 0)
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
  if (name.includes('search')) return Search
  if (name.includes('code') || name.includes('python') || name.includes('javascript')) return Code
  if (name.includes('db') || name.includes('sql') || name.includes('query')) return Database
  if (name.includes('web') || name.includes('http') || name.includes('url')) return Globe
  if (name.includes('skill')) return Settings
  return Zap
})

// 辅助函数
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
  return JSON.stringify(toolArgs.value, null, 2)
})

const formattedResult = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  if (typeof content === 'object') {
    return JSON.stringify(content, null, 2)
  }
  try {
    const parsed = JSON.parse(content)
    return JSON.stringify(parsed, null, 2)
  } catch {
    return content
  }
})

// ============ 7. Todo Write ============
const todoSummary = computed(() => {
  if (!toolResult.value) return ''
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.summary || ''
  } catch {
    return ''
  }
})

const todoTasks = computed(() => {
  if (!toolResult.value) return []
  const content = toolResult.value.content
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.tasks || []
  } catch {
    return []
  }
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
    'pending': 'Pending',
    'in_progress': 'In Progress',
    'failed': 'Failed'
  }
  return labelMap[status] || status
}
</script>

<style scoped>
.shell-container {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
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
