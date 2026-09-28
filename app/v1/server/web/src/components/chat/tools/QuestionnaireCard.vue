<template>
  <div class="questionnaire-card w-full max-w-md">
    <!-- 工具调用卡片 -->
    <div 
      class="tool-call-card bg-card border rounded-lg overflow-hidden transition-all border-primary"
      :class="isFormInteractive ? 'hover:border-primary/30 cursor-default' : 'hover:border-primary/50 cursor-pointer'"
      @click="handleClick"
    >
      <!-- 头部：始终显示 -->
      <div class="flex items-center gap-3 p-3">
        <div class="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
          <ClipboardList class="w-4 h-4 text-primary" />
        </div>
        <div class="flex-1 min-w-0">
          <div class="font-medium text-sm truncate">{{ t('tools.questionnaire.title') }}：{{ title }}</div>
          <div class="text-xs text-muted-foreground flex items-center gap-2 mt-0.5">
            <span v-if="isPending" class="flex items-center gap-1 text-blue-600">
              <Loader2 class="w-3 h-3 animate-spin" />
              {{ t('tools.questionnaire.waiting') }}
            </span>
            <span v-else-if="isSubmitted" class="flex items-center gap-1 text-green-600">
              <CheckCircle class="w-3 h-3" />
              {{ t('tools.questionnaire.completed') }}
            </span>
            <span v-else-if="isExpired" class="flex items-center gap-1 text-orange-600">
              <Clock class="w-3 h-3" />
              {{ t('tools.questionnaire.expired') }}
            </span>
          </div>
        </div>
      </div>

      <!-- 展开内容：问卷表单或历史结果 -->
      <div class="border-t">
        <!-- 历史记录：显示已完成状态和答案 -->
        <div v-if="hasToolResult" class="questionnaire-form bg-card p-4 space-y-4" @click.stop>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2 text-green-600">
              <CheckCircle class="w-5 h-5" />
              <span class="font-medium">{{ t('tools.questionnaire.alreadyCompleted') }}</span>
            </div>
            <Badge v-if="isAutoSubmit" variant="outline" class="text-xs">
              {{ t('tools.questionnaire.autoSubmitted') }}
            </Badge>
            <Badge v-else variant="outline" class="text-xs">
              {{ t('tools.questionnaire.manuallySubmitted') }}
            </Badge>
          </div>
          
          <!-- 显示问题和答案 -->
          <div class="space-y-3">
            <div 
              v-for="question in questions" 
              :key="question.id"
              class="question-result p-3 rounded-md bg-muted/30"
            >
              <div class="mb-2">
                <MarkdownRenderer :content="question.title" class="question-markdown text-sm" />
              </div>
              <div class="text-sm text-green-600">
                <span v-if="question.type === 'multiple_choice'">
                  {{ formatMultipleChoiceAnswer(question, answers[question.id]) }}
                </span>
                <span v-else-if="question.type === 'single_choice'">
                  {{ formatSingleChoiceAnswer(question, answers[question.id]) }}
                </span>
                <span v-else>
                  {{ answers[question.id] || '-' }}
                </span>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 实时问卷：显示表单 -->
        <div v-else class="questionnaire-form bg-card p-4 space-y-4" @click.stop>
          <!-- 提示信息 -->
          <div v-if="!isSubmitted && !isExpired" class="bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 rounded-md p-3 text-sm text-blue-800 dark:text-blue-200 flex items-start gap-2">
            <Info class="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div>
              <p class="font-medium">{{ t('tools.questionnaire.pleaseAnswer') }}</p>
              <p class="text-xs text-blue-600 dark:text-blue-300 mt-1">{{ t('tools.questionnaire.submitTip') }}</p>
            </div>
          </div>

          <!-- 倒计时 -->
          <div v-if="!isSubmitted && !isExpired" class="flex items-center justify-between text-sm">
            <span class="text-muted-foreground">{{ t('tools.questionnaire.remainingTime') }}</span>
            <span 
              class="font-mono px-2 py-1 rounded"
              :class="{ 
                'bg-yellow-100 text-yellow-800': remainingTime <= 60 && remainingTime > 0,
                'bg-red-100 text-red-800': remainingTime <= 0,
                'bg-blue-100 text-blue-800': remainingTime > 60
              }"
            >
              {{ formatTime(remainingTime) }}
            </span>
          </div>

          <!-- 问题列表 -->
          <div class="space-y-4">
            <div 
              v-for="question in questions" 
              :key="question.id"
              class="question-item space-y-2 p-3 rounded-md bg-muted/30"
            >
              <div class="question-title">
                <MarkdownRenderer :content="question.title" class="question-markdown text-sm" />
              </div>

              <!-- 单选题 -->
              <RadioGroup 
                v-if="question.type === 'single_choice'"
                v-model="answers[question.id]"
                class="space-y-1 mt-2"
                :disabled="isSubmitted || isExpired"
              >
                <div 
                  v-for="option in question.options" 
                  :key="option.value"
                  class="flex items-center space-x-2 p-1.5 rounded hover:bg-muted/50 cursor-pointer"
                  @click.stop="selectSingleChoice(question.id, option.value)"
                >
                  <RadioGroupItem :value="option.value" :id="`${question.id}-${option.value}`" />
                  <Label :for="`${question.id}-${option.value}`" class="text-sm cursor-pointer flex-1">
                    {{ option.label }}
                  </Label>
                </div>
              </RadioGroup>

              <!-- 多选题 -->
              <div v-else-if="question.type === 'multiple_choice'" class="space-y-1 mt-2">
                <div 
                  v-for="option in question.options" 
                  :key="option.value"
                  class="flex items-center space-x-2 p-1.5 rounded hover:bg-muted/50 cursor-pointer"
                  @click.stop="toggleCheck(question.id, option.value)"
                >
                  <Checkbox 
                    :id="`${question.id}-${option.value}`"
                    :checked="isChecked(question.id, option.value)"
                    :disabled="isSubmitted || isExpired"
                  />
                  <Label :for="`${question.id}-${option.value}`" class="text-sm cursor-pointer flex-1">
                    {{ option.label }}
                  </Label>
                </div>
              </div>

              <!-- 文本题 -->
              <Textarea
                v-else-if="question.type === 'text'"
                v-model="answers[question.id]"
                :placeholder="question.placeholder || '请输入...'"
                :maxlength="question.max_length || 1000"
                :disabled="isSubmitted || isExpired"
                rows="3"
                class="mt-2 resize-none"
              />
            </div>
          </div>

          <!-- 提交按钮 -->
          <div class="flex items-center justify-between pt-2 border-t">
            <div class="text-sm">
              <span v-if="isExpired" class="text-red-500 flex items-center gap-1">
                <AlertCircle class="w-4 h-4" />
                {{ t('tools.questionnaire.autoSubmitting') }}
              </span>
              <span v-else-if="isSubmitted" class="text-green-600 flex items-center gap-1">
                <CheckCircle class="w-4 h-4" />
                {{ t('tools.questionnaire.submitted') }}
              </span>
              <span v-else class="text-muted-foreground text-xs">
                {{ t('tools.questionnaire.allOptional') }}
              </span>
            </div>
            <Button 
              @click.stop="submit" 
              :disabled="isSubmitting || isExpired || isSubmitted"
              :variant="isSubmitted ? 'outline' : 'default'"
            >
              <Loader2 v-if="isSubmitting" class="w-4 h-4 mr-2 animate-spin" />
              <CheckCircle v-else-if="isSubmitted" class="w-4 h-4 mr-2" />
              <Send v-else class="w-4 h-4 mr-2" />
              {{ isSubmitting ? t('tools.questionnaire.submitting') : isSubmitted ? t('tools.questionnaire.submitted') : t('tools.questionnaire.submit') }}
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Checkbox } from '@/components/ui/checkbox'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { 
  ClipboardList, 
  Loader2, 
  CheckCircle, 
  Clock, 
  Info, 
  AlertCircle, 
  Send 
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useLanguage } from '@/utils/i18n'
import request from '@/utils/request'
import MarkdownRenderer from '../MarkdownRenderer.vue'

const { t } = useLanguage()

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: Object,
    default: null
  },
  message: {
    type: Object,
    default: null
  },
  openWorkbench: {
    type: Function,
    default: null
  }
})

const emit = defineEmits(['click'])

const answers = ref({})
const isSubmitting = ref(false)
const submitStatus = ref('pending') // pending, submitted, expired
const remainingTime = ref(300)
const isAutoSubmit = ref(false) // 是否为自动提交
const submittedAt = ref(null) // 提交时间
let countdownTimer = null
let interruptionListener = null

// 解析工具参数
const sessionId = computed(() => {
  const args = props.toolCall.function?.arguments
  if (typeof args === 'string') {
    try {
      const parsed = JSON.parse(args)
      return parsed.questionnaire_id || ''
    } catch {
      return ''
    }
  }
  return args?.questionnaire_id || ''
})

const title = computed(() => {
  const args = props.toolCall.function?.arguments
  if (typeof args === 'string') {
    try {
      return JSON.parse(args).title || t('tools.questionnaire.title')
    } catch {
      return t('tools.questionnaire.title')
    }
  }
  return args?.title || t('tools.questionnaire.title')
})

const questions = computed(() => {
  const args = props.toolCall.function?.arguments
  if (typeof args === 'string') {
    try {
      return JSON.parse(args).questions || []
    } catch {
      return []
    }
  }
  return args?.questions || []
})

const waitTime = computed(() => {
  const args = props.toolCall.function?.arguments
  if (typeof args === 'string') {
    try {
      return JSON.parse(args).wait_time || 300
    } catch {
      return 300
    }
  }
  return args?.wait_time || 300
})

// 获取消息时间戳
const messageTimestamp = computed(() => {
  // 从 message 或 toolCall 中获取时间戳
  const ts = props.message?.timestamp || props.toolCall.timestamp || Date.now()
  // 处理时间戳：如果是秒级（小于 10000000000），转换为毫秒
  const num = Number(ts)
  if (!isNaN(num)) {
    return num < 10000000000 ? num * 1000 : num
  }
  return ts
})

// 检查是否已有工具执行结果（从历史记录加载）
const hasToolResult = computed(() => {
  return props.toolResult !== null && props.toolResult !== undefined
})

const isPending = computed(() => submitStatus.value === 'pending' && !hasToolResult.value && remainingTime.value > 0)
const isSubmitted = computed(() => submitStatus.value === 'submitted' || hasToolResult.value)
const isExpired = computed(() => submitStatus.value === 'expired' || remainingTime.value <= 0)
const isFormInteractive = computed(() => !hasToolResult.value && !isSubmitted.value && !isExpired.value)

// 计算剩余时间（基于消息时间戳）
function calculateRemainingTime() {
  const now = Date.now()
  const messageTime = new Date(messageTimestamp.value).getTime()
  const elapsedSeconds = Math.floor((now - messageTime) / 1000)
  return Math.max(0, waitTime.value - elapsedSeconds)
}

// 从工具结果中提取答案
function extractAnswersFromToolResult(toolResult) {
  if (!toolResult) return null
  try {
    // toolResult 格式: { content: {...} } 或 { content: "..." }
    const content = toolResult.content
    if (!content) return null
    
    // 如果 content 是字符串，解析它
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed?.answers || null
  } catch {
    return null
  }
}

// 从工具结果中提取提交方式
function extractSubmitInfoFromToolResult(toolResult) {
  if (!toolResult) return { isAuto: false, submittedAt: null }
  try {
    // toolResult.content 可能已经是解析后的对象（由 getParsedToolResult 处理过）
    const content = toolResult.content
    if (!content) return { isAuto: false, submittedAt: null }
    
    // content 可能是对象或字符串
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return {
      isAuto: parsed?.is_auto_submit || false,
      submittedAt: parsed?.submitted_at || null
    }
  } catch {
    return { isAuto: false, submittedAt: null }
  }
}

// 初始化
onMounted(() => {
  // 如果已有工具结果，说明是历史记录，显示为已完成
  if (hasToolResult.value) {
    submitStatus.value = 'submitted'
    // 从历史结果中恢复答案
    const extractedAnswers = extractAnswersFromToolResult(props.toolResult)
    if (extractedAnswers) {
      answers.value = extractedAnswers
    }
    // 提取提交方式信息
    const submitInfo = extractSubmitInfoFromToolResult(props.toolResult)
    isAutoSubmit.value = submitInfo.isAuto
    submittedAt.value = submitInfo.submittedAt
    return
  }
  
  // 计算基于消息时间的剩余时间
  const calculatedRemaining = calculateRemainingTime()
  remainingTime.value = calculatedRemaining
  
  // 初始化答案为默认值
  questions.value.forEach(q => {
    if (q.type === 'multiple_choice') {
      answers.value[q.id] = q.default || []
    } else {
      answers.value[q.id] = q.default || ''
    }
  })
  
  // 如果已经超时，标记为过期状态
  // 注意：超时不自动提交，让工具自己去轮询获取默认值
  // 因为后端可能已经删除了 session
  if (calculatedRemaining <= 0) {
    submitStatus.value = 'expired'
    return
  }
  
  startCountdown()

  interruptionListener = (event) => {
    const interruptedSessionId = event?.detail?.sessionId || ''
    if (
      interruptedSessionId !== sessionId.value &&
      !sessionId.value.startsWith(`${interruptedSessionId}__questionnaire__`)
    ) {
      return
    }
    if (submitStatus.value === 'submitted') return
    submitStatus.value = 'expired'
    if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }
  window.addEventListener('questionnaire-session-interrupted', interruptionListener)
})

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
  if (interruptionListener) {
    window.removeEventListener('questionnaire-session-interrupted', interruptionListener)
    interruptionListener = null
  }
})

function startCountdown() {
  if (waitTime.value <= 0) return
  countdownTimer = setInterval(() => {
    remainingTime.value--
    if (remainingTime.value <= 0) {
      clearInterval(countdownTimer)
      autoSubmit()
    }
  }, 1000)
}

function formatTime(seconds) {
  if (seconds <= 0) return '00:00'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

// 格式化单选题答案
function formatSingleChoiceAnswer(question, value) {
  if (!value) return '-'
  const option = question.options?.find(opt => opt.value === value)
  return option?.label || value
}

// 格式化多选题答案
function formatMultipleChoiceAnswer(question, values) {
  if (!values || values.length === 0) return '-'
  const labels = values.map(val => {
    const option = question.options?.find(opt => opt.value === val)
    return option?.label || val
  })
  return labels.join(', ')
}

function isChecked(questionId, value) {
  return answers.value[questionId]?.includes(value) || false
}

function toggleCheck(questionId, value) {
  if (isSubmitted.value || isExpired.value) return
  if (!answers.value[questionId]) answers.value[questionId] = []
  const index = answers.value[questionId].indexOf(value)
  if (index > -1) {
    answers.value[questionId].splice(index, 1)
  } else {
    answers.value[questionId].push(value)
  }
}

function selectSingleChoice(questionId, value) {
  if (isSubmitted.value || isExpired.value) return
  answers.value[questionId] = value
}

async function autoSubmit() {
  if (isSubmitting.value || isSubmitted.value) return
  toast.info(t('tools.questionnaire.autoSubmitToast'))
  await doSubmit(true)  // true 表示自动提交
}

async function submit() {
  if (isSubmitting.value || isSubmitted.value || isExpired.value) return
  await doSubmit(false)  // false 表示手动提交
}

async function doSubmit(isAuto = false) {
  isSubmitting.value = true
  try {
    const encodedSessionId = encodeURIComponent(sessionId.value)
    const response = await request.post(`/api/questionnaires/${encodedSessionId}/submit`, {
      answers: answers.value,
      title: title.value,
      questions: questions.value,
      wait_time: waitTime.value,
      is_auto_submit: isAuto
    })

    submitStatus.value = 'submitted'
    toast.success(t('tools.questionnaire.submitSuccessToast'))
  } catch (err) {
    toast.error(t('tools.questionnaire.submitError') + ': ' + (err.message || t('tools.questionnaire.tryAgain')))
  } finally {
    isSubmitting.value = false
  }
}

// 处理点击事件，跳转到工作台
const handleClick = (event) => {
  if (isFormInteractive.value) {
    return
  }

  // 如果点击的是按钮，不触发跳转（让按钮自己处理）
  if (event?.target?.closest('button')) {
    return
  }
  
  console.log('[QuestionnaireCard] Opening workbench for', props.toolCall?.id)
  
  // 优先使用 openWorkbench prop
  if (props.openWorkbench) {
    props.openWorkbench({ toolCallId: props.toolCall.id, realtime: false })
  } else {
    // 回退到 emit 事件
    emit('click', props.toolCall, props.toolResult)
  }
}
</script>

<style scoped>
.question-markdown :deep(.prose) {
  margin: 0;
  max-width: none;
}

.question-markdown :deep(.prose p) {
  margin: 0.25rem 0;
}

.question-markdown :deep(.prose ul),
.question-markdown :deep(.prose ol) {
  margin: 0.35rem 0;
  padding-left: 1.1rem;
}

.question-markdown :deep(.prose li) {
  margin: 0.1rem 0;
}
</style>

<style scoped>
.questionnaire-card {
  margin: 0.5rem 0;
}
.tool-call-card {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
</style>
