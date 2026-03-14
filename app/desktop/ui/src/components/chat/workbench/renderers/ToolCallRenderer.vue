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
          <div v-if="shellOutput" class="shell-output whitespace-pre-wrap">{{ shellOutput }}</div>
          <div v-if="shellError" class="shell-error text-red-400 mt-2">{{ shellError }}</div>
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
      <template v-else-if="isFileRead">
        <div class="h-full flex flex-col">
          <div class="file-header px-4 py-3 border-b border-border flex items-center gap-2 flex-none">
            <FileText class="w-4 h-4" />
            <span class="font-medium text-sm">{{ readFilePath }}</span>
            <Badge variant="secondary" class="text-xs">{{ readFileType }}</Badge>
          </div>
          <div class="file-content flex-1 overflow-auto p-4">
            <!-- 代码文件 -->
            <SyntaxHighlighter
              v-if="isCodeFile(readFileType)"
              :code="fileContent"
              :language="readFileType"
            />
            <!-- Markdown -->
            <MarkdownRenderer
              v-else-if="readFileType === 'markdown'"
              :content="fileContent"
            />
            <!-- 图片 -->
            <img
              v-else-if="isImageFile(readFileType)"
              :src="fileContent"
              class="max-w-full h-auto"
            />
            <!-- 其他文本 -->
            <pre v-else class="whitespace-pre-wrap text-sm">{{ fileContent }}</pre>
          </div>
        </div>
      </template>

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

      <!-- 5. todo_write - 任务列表渲染 -->
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

      <!-- 6. sys_spawn_agent - Agent 创建结果展示 -->
      <template v-else-if="isSysSpawnAgent">
        <div class="sys-spawn-agent-container h-full flex flex-col">
          <!-- 加载中状态 -->
          <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span>正在创建智能体...</span>
          </div>
          <!-- 错误状态 -->
          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-medium">创建失败</p>
              <p class="text-sm opacity-80 mt-1">{{ spawnAgentError }}</p>
            </div>
          </div>
          <!-- 成功状态 - 与工作台融为一体 -->
          <div v-else class="flex flex-col h-full">
            <!-- Agent 信息 -->
            <div class="flex items-start gap-3 p-4 pb-3 border-b border-border/30">
              <img :src="spawnAgentAvatarUrl" :alt="spawnAgentName" class="w-10 h-10 rounded-lg bg-muted object-cover flex-shrink-0" />
              <div class="flex-1 min-w-0">
                <h4 class="font-medium text-sm text-foreground">{{ spawnAgentName || '未命名智能体' }}</h4>
                <p class="text-xs text-muted-foreground mt-0.5">{{ spawnAgentDescription || '暂无描述' }}</p>
              </div>
              <Button variant="ghost" size="sm" class="h-7 text-xs" @click="openSpawnedAgentChat">
                <MessageSquare class="w-3.5 h-3.5 mr-1" />
                开始对话
              </Button>
            </div>
            <!-- 系统提示词 - 使用 Markdown 渲染，占满剩余空间 -->
            <div v-if="spawnAgentSystemPrompt" class="flex-1 min-h-0 overflow-hidden">
              <div class="h-full overflow-auto custom-scrollbar p-4">
                <MarkdownRenderer :content="spawnAgentSystemPrompt" class="text-xs" />
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 7. sys_delegate_task - 任务委派展示 -->
      <template v-else-if="isSysDelegateTask">
        <div class="sys-delegate-task-container h-full flex flex-col">
          <!-- 任务委派可视化 - 始终显示 -->
          <div class="flex items-center justify-center gap-6 py-4 border-b border-border/30 bg-muted/20 flex-shrink-0">
            <!-- Source Agent -->
            <div class="flex flex-col items-center gap-2 w-[100px]">
              <div class="relative">
                <img 
                  :src="currentAgentAvatar" 
                  :alt="currentAgentName"
                  class="w-12 h-12 rounded-xl bg-muted object-cover border-2 border-primary/30"
                />
                <div class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-primary flex items-center justify-center">
                  <User class="w-3 h-3 text-primary-foreground" />
                </div>
              </div>
              <span class="text-xs text-muted-foreground">{{ t('workbench.tool.delegator') }}</span>
            </div>

            <!-- Arrow -->
            <div class="flex flex-col items-center gap-1">
              <ArrowRight class="w-5 h-5 text-muted-foreground" />
              <span class="text-xs text-muted-foreground">{{ delegateTasks.length }} {{ t('workbench.tool.tasks') }}</span>
            </div>

            <!-- Target Agents -->
            <div class="flex flex-col items-center gap-2 w-[100px]">
              <div class="flex -space-x-2">
                <img 
                  v-for="(task, idx) in delegateTasks.slice(0, 3)" 
                  :key="idx"
                  :src="getAgentAvatar(task.agent_id)" 
                  :alt="task.agent_id"
                  class="w-10 h-10 rounded-xl bg-muted object-cover border-2 border-background"
                />
                <div v-if="delegateTasks.length > 3" class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center border-2 border-background text-xs font-medium">
                  +{{ delegateTasks.length - 3 }}
                </div>
              </div>
              <span class="text-sm font-medium truncate w-full text-center">{{ delegateTasks.length }} {{ t('workbench.tool.targetAgents') }}</span>
            </div>
          </div>

          <!-- 任务列表 - 可滚动，显示完整描述 - 始终显示 -->
          <div class="flex-1 overflow-auto p-4 space-y-3 custom-scrollbar">
            <div 
              v-for="(task, index) in delegateTasks" 
              :key="index"
              class="border rounded-lg p-3 hover:bg-muted/30 transition-colors"
            >
              <div class="flex items-start gap-3">
                <img 
                  :src="getAgentAvatar(task.agent_id)" 
                  :alt="task.agent_id"
                  class="w-10 h-10 rounded-lg bg-muted object-cover flex-shrink-0"
                />
                <div class="flex-1 min-w-0">
                  <div class="flex items-center justify-between mb-1">
                    <p class="text-sm font-medium truncate">{{ task.task_name || task.original_task || t('workbench.tool.untitledTask') }}</p>
                    <Badge v-if="task.session_id" variant="outline" class="text-xs flex-shrink-0 ml-2">
                      {{ t('workbench.tool.hasSession') }}
                    </Badge>
                  </div>
                  <p class="text-xs text-muted-foreground truncate mb-2">{{ getAgentName(task.agent_id) }}</p>
                  <!-- 完整任务描述 -->
                  <div class="bg-muted/30 rounded p-2 max-h-[150px] overflow-y-auto custom-scrollbar">
                    <pre class="text-xs whitespace-pre-wrap font-mono">{{ task.content }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 加载中状态 -->
          <div v-if="!toolResult" class="flex items-center justify-center p-4 border-t border-border/30 bg-muted/10">
            <Loader2 class="w-5 h-5 animate-spin mr-2 text-primary" />
            <span class="text-sm text-muted-foreground">{{ t('workbench.tool.delegatingTasks') }}</span>
          </div>

          <!-- 错误状态 -->
          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 border-t border-border/30 bg-destructive/5">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5 text-destructive" />
            <div>
              <p class="font-medium text-destructive">{{ t('workbench.tool.delegationFailed') }}</p>
              <p class="text-sm opacity-80 mt-1">{{ delegationError }}</p>
            </div>
          </div>

          <!-- 结果展示 - 有结果时显示 -->
          <div v-else-if="delegationResult" class="border-t border-border/30 p-4 bg-green-500/5">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <CheckCircle class="w-4 h-4 text-green-600" />
                <span class="text-sm font-medium text-green-700">{{ t('workbench.tool.delegationCompleted') }}</span>
              </div>
              <Button 
                variant="ghost" 
                size="sm" 
                class="h-6 text-xs gap-1"
                @click="showDelegationResult = !showDelegationResult"
              >
                <Eye v-if="!showDelegationResult" class="w-3.5 h-3.5" />
                <EyeOff v-else class="w-3.5 h-3.5" />
                {{ showDelegationResult ? t('workbench.tool.hideResult') : t('workbench.tool.viewResult') }}
              </Button>
            </div>
            <div v-if="showDelegationResult" class="max-h-[200px] overflow-auto custom-scrollbar bg-background rounded p-2">
              <MarkdownRenderer :content="delegationResult" class="text-xs" />
            </div>
          </div>
        </div>
      </template>

      <!-- 8. sys_finish_task - 任务完成结果展示 -->
      <template v-else-if="isSysFinishTask">
        <div class="sys-finish-task-container h-full flex flex-col">
          <!-- 加载中状态 -->
          <div v-if="!toolResult" class="flex items-center justify-center h-full text-muted-foreground p-4">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span>{{ t('workbench.tool.finishingTask') }}</span>
          </div>
          <!-- 错误状态 -->
          <div v-else-if="toolResult?.is_error" class="flex items-start gap-3 p-4 text-destructive">
            <XCircle class="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <p class="font-medium">{{ t('workbench.tool.finishFailed') }}</p>
              <p class="text-sm opacity-80 mt-1">{{ finishTaskError }}</p>
            </div>
          </div>
          <!-- 成功状态 -->
          <div v-else class="flex flex-col h-full overflow-hidden">
            <!-- 状态头部 -->
            <div class="flex items-center gap-3 p-4 border-b border-border/30 bg-green-500/5 flex-shrink-0">
              <div class="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center">
                <CheckCircle class="w-5 h-5 text-green-600" />
              </div>
              <div>
                <p class="font-medium text-sm">{{ t('workbench.tool.taskCompleted') }}</p>
                <p class="text-xs text-muted-foreground">{{ finishTaskStatus }}</p>
              </div>
            </div>
            <!-- 结果内容 - Markdown 渲染 -->
            <div class="flex-1 overflow-hidden">
              <div class="h-full overflow-auto custom-scrollbar p-4">
                <MarkdownRenderer :content="finishTaskResult" class="text-sm" />
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 9. execute_python_code / execute_javascript_code - IDE 样式 -->
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
  EyeOff
} from 'lucide-vue-next'
import SyntaxHighlighter from '../../SyntaxHighlighter.vue'
import MarkdownRenderer from '../../MarkdownRenderer.vue'
import { skillAPI } from '@/api/skill.js'
import { useLanguage } from '@/utils/i18n'

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
const isCodeExecution = computed(() =>
  toolName.value === 'execute_python_code' ||
  toolName.value === 'execute_javascript_code'
)
const isTodoWrite = computed(() => toolName.value === 'todo_write')
const isSysSpawnAgent = computed(() => toolName.value === 'sys_spawn_agent')
const isSysDelegateTask = computed(() => toolName.value === 'sys_delegate_task')
const isSysFinishTask = computed(() => toolName.value === 'sys_finish_task')

// 显示名称映射
const displayToolName = computed(() => {
  const nameMap = {
    'execute_shell_command': t('workbench.tool.shellCommand'),
    'load_skill': t('workbench.tool.loadSkill'),
    'file_read': t('workbench.tool.readFile'),
    'file_write': t('workbench.tool.writeFile'),
    'execute_python_code': t('workbench.tool.pythonCode'),
    'execute_javascript_code': t('workbench.tool.jsCode')
  }
  return nameMap[toolName.value] || toolName.value
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

// ============ 3. File Read ============
const readFilePath = computed(() => toolArgs.value.file_path || '')
const readFileType = computed(() => {
  const path = readFilePath.value
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
    'sh': 'bash',
    'png': 'image',
    'jpg': 'image',
    'jpeg': 'image',
    'gif': 'image',
    'svg': 'image'
  }
  return typeMap[ext] || ext || 'text'
})
const fileContent = computed(() => {
  const content = toolResult.value?.content
  if (!content) return ''
  try {
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed.content || parsed.data || parsed
  } catch {
    return content
  }
})

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

// ============ 6. 其他工具 ============
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

const isImageFile = (type) => {
  return type === 'image'
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

// ============ 8. Sys Delegate Task ============
const delegateTasks = computed(() => toolArgs.value.tasks || [])
const showDelegationResult = ref(false)

// Get current agent info from item
const currentAgentId = computed(() => {
  // Try to get agent_id from item metadata or data
  return props.item?.agent_id || props.item?.data?.agent_id || ''
})

const currentAgentName = computed(() => {
  // Try to get from item metadata or use default
  return props.item?.agent_name || props.item?.data?.agent_name || t('workbench.tool.delegator')
})

const currentAgentAvatar = computed(() => {
  const agentId = currentAgentId.value
  if (!agentId) {
    return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=current`
  }
  return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}`
})

const getAgentAvatar = (agentId) => {
  if (!agentId) return ''
  return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agentId)}`
}

const getAgentName = (agentId) => {
  if (!agentId) return 'Unknown'
  return agentId.length > 15 ? agentId.slice(0, 12) + '...' : agentId
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
