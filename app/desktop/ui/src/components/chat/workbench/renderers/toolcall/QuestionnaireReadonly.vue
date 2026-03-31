<template>
  <div class="questionnaire-readonly space-y-4">
    <!-- 标题和状态 -->
    <div class="flex items-center gap-2 text-sm font-medium">
      <ClipboardList class="w-4 h-4 text-muted-foreground" />
      <span class="truncate">{{ title }}</span>
      <template v-if="hasResult">
        <Badge variant="default" class="text-[10px] h-4 px-1 bg-green-500">{{ t('tools.questionnaire.completed') }}</Badge>
        <Badge v-if="submitInfo.isAuto" variant="outline" class="text-[10px] h-4 px-1">{{ t('tools.questionnaire.autoSubmitted') }}</Badge>
        <Badge v-else variant="outline" class="text-[10px] h-4 px-1">{{ t('tools.questionnaire.manuallySubmitted') }}</Badge>
      </template>
    </div>

    <!-- 有结果：显示所有问题、选项和答案 -->
    <div v-if="hasResult" class="space-y-5">
      <div 
        v-for="(question, idx) in questions" 
        :key="question.id"
        class="text-sm"
      >
        <div class="mb-2 text-foreground">
          <MarkdownRenderer :content="`${idx + 1}. ${question.title}`" class="question-markdown text-sm" />
        </div>
        
        <!-- 单选题：显示所有选项和选中状态 -->
        <div v-if="question.type === 'single_choice'" class="space-y-1.5 pl-1">
          <div 
            v-for="option in question.options" 
            :key="option.value"
            class="flex items-center gap-2 text-xs py-0.5"
            :class="answers[question.id] === option.value ? 'text-green-600 font-medium' : 'text-muted-foreground'"
          >
            <span class="w-4 h-4 rounded-full border flex items-center justify-center text-[8px] flex-shrink-0"
              :class="answers[question.id] === option.value ? 'border-green-600 bg-green-600 text-white' : 'border-muted-foreground'"
            >
              <span v-if="answers[question.id] === option.value">✓</span>
            </span>
            <span>{{ option.label }}</span>
          </div>
        </div>
        
        <!-- 多选题：显示所有选项和选中状态 -->
        <div v-else-if="question.type === 'multiple_choice'" class="space-y-1.5 pl-1">
          <div 
            v-for="option in question.options" 
            :key="option.value"
            class="flex items-center gap-2 text-xs py-0.5"
            :class="(answers[question.id] || []).includes(option.value) ? 'text-green-600 font-medium' : 'text-muted-foreground'"
          >
            <span class="w-4 h-4 rounded border flex items-center justify-center text-[8px] flex-shrink-0"
              :class="(answers[question.id] || []).includes(option.value) ? 'border-green-600 bg-green-600 text-white' : 'border-muted-foreground'"
            >
              <span v-if="(answers[question.id] || []).includes(option.value)">✓</span>
            </span>
            <span>{{ option.label }}</span>
          </div>
        </div>
        
        <!-- 文本题：显示答案 -->
        <div v-else class="pl-1">
          <div class="text-green-600 text-sm bg-green-50/50 dark:bg-green-950/20 px-3 py-2 rounded">
            {{ answers[question.id] || '-' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 无结果：显示问题预览 -->
    <div v-else class="space-y-2">
      <div 
        v-for="(question, idx) in questions.slice(0, 3)" 
        :key="question.id"
        class="text-xs text-muted-foreground flex items-start gap-2"
      >
        <span class="flex-shrink-0">{{ idx + 1 }}.</span>
        <span class="flex-1 min-w-0">
          <MarkdownRenderer :content="question.title" class="question-markdown text-xs" />
        </span>
        <Badge v-if="question.type === 'multiple_choice'" variant="outline" class="text-[10px] h-4 px-1">{{ t('tools.questionnaire.multipleChoice') }}</Badge>
        <Badge v-else-if="question.type === 'single_choice'" variant="outline" class="text-[10px] h-4 px-1">{{ t('tools.questionnaire.singleChoice') }}</Badge>
        <Badge v-else variant="outline" class="text-[10px] h-4 px-1">{{ t('tools.questionnaire.text') }}</Badge>
      </div>
      <div v-if="questions.length > 3" class="text-xs text-muted-foreground pl-4">
        ... {{ t('tools.questionnaire.moreQuestions', { count: questions.length - 3 }) }}
      </div>
    </div>

    <!-- 状态提示 -->
    <div v-if="!hasResult" class="space-y-2 pt-2 border-t border-border/50">
      <div class="flex items-center gap-2 text-xs">
        <Info class="w-3 h-3 text-blue-500" />
        <span class="text-muted-foreground">{{ t('tools.questionnaire.fillInMessageList') }}</span>
      </div>
      <div class="text-xs text-amber-600 bg-amber-50/80 dark:bg-amber-950/20 rounded px-3 py-2">
        {{ t('tools.questionnaire.workbenchReadonlyHint') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ClipboardList, Info } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { useLanguage } from '@/utils/i18n'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'

const { t } = useLanguage()

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  },
  toolResult: {
    type: Object,
    default: null
  }
})

// 是否有工具执行结果
const hasResult = computed(() => {
  return props.toolResult !== null && props.toolResult !== undefined
})

// 解析工具参数
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

// 从工具结果中解析答案
const answers = computed(() => {
  if (!hasResult.value) return {}
  try {
    // toolResult 格式: { content: {...} } 或 { content: "..." }
    const content = props.toolResult.content
    if (!content) return {}
    
    // 如果 content 是字符串，解析它
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return parsed?.answers || {}
  } catch {
    return {}
  }
})

// 从工具结果中提取提交方式信息
const submitInfo = computed(() => {
  if (!hasResult.value) return { isAuto: false, submittedAt: null }
  try {
    const content = props.toolResult.content
    if (!content) return { isAuto: false, submittedAt: null }
    
    const parsed = typeof content === 'string' ? JSON.parse(content) : content
    return {
      isAuto: parsed?.is_auto_submit || false,
      submittedAt: parsed?.submitted_at || null
    }
  } catch {
    return { isAuto: false, submittedAt: null }
  }
})

// 格式化答案显示
function formatAnswer(question, value) {
  if (!value || (Array.isArray(value) && value.length === 0)) return '-'
  
  if (question.type === 'single_choice') {
    const option = question.options?.find(opt => opt.value === value)
    return option?.label || value
  }
  
  if (question.type === 'multiple_choice') {
    const labels = value.map(val => {
      const option = question.options?.find(opt => opt.value === val)
      return option?.label || val
    })
    return labels.join(', ')
  }
  
  return value
}
</script>

<style scoped>
.question-markdown :deep(.prose) {
  margin: 0;
  max-width: none;
}

.question-markdown :deep(.prose p) {
  margin: 0.2rem 0;
}

.question-markdown :deep(.prose ul),
.question-markdown :deep(.prose ol) {
  margin: 0.3rem 0;
  padding-left: 1rem;
}
</style>
