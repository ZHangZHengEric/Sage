<template>
  <div class="questionnaire-form bg-card border rounded-lg p-4 space-y-4">
    <!-- 标题和倒计时 -->
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-semibold">{{ title }}</h3>
      <div 
        class="countdown text-sm font-mono px-2 py-1 rounded"
        :class="{ 
          'bg-yellow-100 text-yellow-800': remainingTime <= 30 && remainingTime > 0,
          'bg-red-100 text-red-800': remainingTime <= 0,
          'bg-muted text-muted-foreground': remainingTime > 30
        }"
      >
        {{ formatTime(remainingTime) }}
      </div>
    </div>

    <!-- 问题列表 -->
    <div class="space-y-4">
      <div 
        v-for="question in questions" 
        :key="question.id"
        class="question-item space-y-2"
      >
        <div class="question-title">
          <MarkdownRenderer :content="question.title" class="question-markdown text-sm" />
        </div>
        <p v-if="question.description" class="text-xs text-muted-foreground">
          {{ question.description }}
        </p>

        <!-- 单选题 -->
        <RadioGroup 
          v-if="question.type === 'single_choice'"
          v-model="answers[question.id]"
          class="space-y-1"
        >
          <div 
            v-for="option in question.options" 
            :key="option.value"
            class="flex items-center space-x-2"
          >
            <RadioGroupItem :value="option.value" :id="`${question.id}-${option.value}`" />
            <Label :for="`${question.id}-${option.value}`" class="text-sm cursor-pointer">
              {{ option.label }}
            </Label>
          </div>
        </RadioGroup>

        <!-- 多选题 -->
        <div v-else-if="question.type === 'multiple_choice'" class="space-y-1">
          <div 
            v-for="option in question.options" 
            :key="option.value"
            class="flex items-center space-x-2"
          >
            <Checkbox 
              :id="`${question.id}-${option.value}`"
              :checked="isChecked(question.id, option.value)"
              @update:checked="toggleCheck(question.id, option.value)"
            />
            <Label :for="`${question.id}-${option.value}`" class="text-sm cursor-pointer">
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
          rows="3"
        />
      </div>
    </div>

    <!-- 提交按钮 -->
    <div class="flex items-center justify-between pt-2">
      <span v-if="isExpired" class="text-sm text-red-500">
        已超时，自动提交中...
      </span>
      <Button 
        @click="submit" 
        :disabled="!isValid || isSubmitting || isExpired"
        :loading="isSubmitting"
      >
        {{ isSubmitting ? '提交中...' : '提交' }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Checkbox } from '@/components/ui/checkbox'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import MarkdownRenderer from '../MarkdownRenderer.vue'

const props = defineProps({
  questionnaireId: {
    type: String,
    required: true
  },
  title: {
    type: String,
    required: true
  },
  questions: {
    type: Array,
    required: true
  },
  waitTime: {
    type: Number,
    default: 300
  }
})

const emit = defineEmits(['submit'])

const answers = ref({})
const isSubmitting = ref(false)
const remainingTime = ref(props.waitTime)
let countdownTimer = null

// 初始化答案
onMounted(() => {
  props.questions.forEach(q => {
    if (q.type === 'multiple_choice') {
      // 多选题：使用 default 数组或空数组
      answers.value[q.id] = q.default || []
    } else {
      // 单选或文本题：使用 default 值或空字符串
      answers.value[q.id] = q.default || ''
    }
  })
  startCountdown()
})

onUnmounted(() => {
  if (countdownTimer) {
    clearInterval(countdownTimer)
  }
})

// 是否已过期
const isExpired = computed(() => remainingTime.value <= 0)

// 所有问题都是可选的，始终有效
const isValid = computed(() => true)

// 倒计时
function startCountdown() {
  if (props.waitTime <= 0) return
  
  countdownTimer = setInterval(() => {
    remainingTime.value--
    if (remainingTime.value <= 0) {
      clearInterval(countdownTimer)
      autoSubmit()
    }
  }, 1000)
}

// 格式化时间
function formatTime(seconds) {
  if (seconds <= 0) return '00:00'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

// 检查多选框是否选中
function isChecked(questionId, value) {
  return answers.value[questionId]?.includes(value) || false
}

// 切换多选框
function toggleCheck(questionId, value) {
  if (!answers.value[questionId]) {
    answers.value[questionId] = []
  }
  const index = answers.value[questionId].indexOf(value)
  if (index > -1) {
    answers.value[questionId].splice(index, 1)
  } else {
    answers.value[questionId].push(value)
  }
}

// 自动提交（超时）
async function autoSubmit() {
  if (isSubmitting.value) return
  
  // 填充默认答案
  const finalAnswers = {}
  props.questions.forEach(q => {
    if (q.type === 'multiple_choice') {
      finalAnswers[q.id] = answers.value[q.id] || []
    } else {
      finalAnswers[q.id] = answers.value[q.id] || ''
    }
  })
  
  await doSubmit(finalAnswers)
}

// 手动提交
async function submit() {
  await doSubmit(answers.value)
}

// 执行提交
async function doSubmit(finalAnswers) {
  isSubmitting.value = true
  try {
    const encodedSessionId = encodeURIComponent(props.questionnaireId)
    const response = await fetch(`/api/questionnaires/${encodedSessionId}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        answers: finalAnswers,
        title: props.title,
        questions: props.questions,
        wait_time: props.waitTime
      })
    })

    if (response.ok) {
      emit('submit', { success: true, answers: finalAnswers })
    } else {
      const error = await response.json()
      emit('submit', { success: false, error: error.detail || '提交失败' })
    }
  } catch (err) {
    emit('submit', { success: false, error: err.message })
  } finally {
    isSubmitting.value = false
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
