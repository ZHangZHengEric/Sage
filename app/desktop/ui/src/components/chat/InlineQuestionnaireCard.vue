<template>
  <div class="questionnaire-card w-full max-w-md">
    <div class="rounded-lg border border-border/70 bg-white/85 shadow-sm backdrop-blur-xl transition-colors dark:bg-card/80">
      <div class="flex items-center gap-3 border-b border-border/70 p-3">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <ClipboardList class="h-4 w-4" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium text-foreground">
            {{ questionnaire.title || t('tools.questionnaire.title') }}
          </div>
        </div>
        <Badge v-if="submitted" variant="outline" class="text-[10px]">
          {{ t('tools.questionnaire.completed') }}
        </Badge>
        <div v-else-if="questionnaire.questions.length > 1" class="text-xs font-medium text-muted-foreground">
          {{ currentIndex + 1 }}/{{ questionnaire.questions.length }}
        </div>
      </div>

      <div v-if="questionnaire.questions.length > 1" class="h-1 bg-muted/50">
        <div
          class="h-full rounded-full bg-primary/80 transition-[width] duration-200"
          :style="{ width: `${progress}%` }"
        />
      </div>

      <div class="space-y-4 p-4">
        <InlineQuestionnaireResponse
          v-if="submittedResponse"
          :response="submittedResponse"
        />

        <template v-else-if="currentQuestion">
          <div class="space-y-3 rounded-md bg-muted/30 p-3">
            <div class="text-sm font-medium leading-6 text-foreground">
              {{ currentQuestion.text }}
            </div>

            <div v-if="currentQuestion.type === 'single_choice'" class="flex flex-wrap gap-2">
              <button
                v-for="option in currentQuestion.options"
                :key="option.value"
                type="button"
                class="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="singleValue === option.value ? selectedChoiceClass : idleChoiceClass"
                :disabled="!canEdit"
                @click="setSingleValue(option.value)"
              >
                <CircleDot v-if="singleValue === option.value" class="h-4 w-4" />
                <Circle v-else class="h-4 w-4" />
                <span>{{ option.label }}</span>
              </button>
              <button
                v-if="currentQuestion.allowOther"
                type="button"
                class="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="singleValue === otherValue ? selectedChoiceClass : idleChoiceClass"
                :disabled="!canEdit"
                @click="setSingleValue(otherValue)"
              >
                <CircleDot v-if="singleValue === otherValue" class="h-4 w-4" />
                <Circle v-else class="h-4 w-4" />
                <span>{{ uiText.other }}</span>
              </button>
            </div>

            <div v-else-if="currentQuestion.type === 'multi_choice'" class="flex flex-wrap gap-2">
              <button
                v-for="option in currentQuestion.options"
                :key="option.value"
                type="button"
                class="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="multiValues.includes(option.value) ? selectedChoiceClass : idleChoiceClass"
                :disabled="!canEdit"
                @click="toggleMultiValue(option.value)"
              >
                <CheckSquare v-if="multiValues.includes(option.value)" class="h-4 w-4" />
                <Square v-else class="h-4 w-4" />
                <span>{{ option.label }}</span>
              </button>
              <button
                v-if="currentQuestion.allowOther"
                type="button"
                class="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="multiValues.includes(otherValue) ? selectedChoiceClass : idleChoiceClass"
                :disabled="!canEdit"
                @click="toggleMultiValue(otherValue)"
              >
                <CheckSquare v-if="multiValues.includes(otherValue)" class="h-4 w-4" />
                <Square v-else class="h-4 w-4" />
                <span>{{ uiText.other }}</span>
              </button>
            </div>

            <Textarea
              v-if="currentQuestion.type === 'free_text'"
              v-model="textValue"
              rows="3"
              class="resize-none bg-background/70"
              :disabled="!canEdit"
            />
            <Textarea
              v-else-if="showOtherInput"
              v-model="otherText"
              rows="2"
              class="resize-none bg-background/70"
              :disabled="!canEdit"
            />
          </div>

          <div class="flex items-center gap-2 border-t border-border/70 pt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              class="h-9 w-10 px-0"
              :disabled="currentIndex === 0 || isSubmitting || submitted"
              @click="goBack"
            >
              <ChevronLeft class="h-4 w-4" />
            </Button>
            <Button
              type="button"
              size="sm"
              class="h-9 flex-1"
              :disabled="isSubmitting || submitted || (isLastQuestion && !canSubmit)"
              @click="handlePrimary"
            >
              <Loader2 v-if="isSubmitting" class="mr-2 h-4 w-4 animate-spin" />
              <template v-else-if="isLastQuestion">
                <Send class="mr-2 h-4 w-4" />
                {{ t('tools.questionnaire.submit') }}
              </template>
              <template v-else>
                {{ t('common.next') || '继续' }}
                <ChevronRight class="ml-2 h-4 w-4" />
              </template>
            </Button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Circle,
  CircleDot,
  ClipboardList,
  Loader2,
  Send,
  Square,
} from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'
import { buildQuestionnaireSubmission, initialQuestionnaireDraft } from '@/utils/inlineQuestionnaire.js'
import InlineQuestionnaireResponse from './InlineQuestionnaireResponse.vue'

const otherValue = '__questionnaire_other__'
const selectedChoiceClass = 'border-primary/60 bg-primary/10 text-primary dark:bg-primary/15'
const idleChoiceClass = 'border-border/80 bg-background/70 text-foreground hover:bg-muted/60'

const props = defineProps({
  questionnaire: {
    type: Object,
    required: true,
  },
  canSubmit: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['submit'])
const { t } = useLanguage()

const draft = ref(initialQuestionnaireDraft(props.questionnaire))
const currentIndex = ref(0)
const isSubmitting = ref(false)
const submittedResponse = ref(null)

const submitted = computed(() => submittedResponse.value !== null)
const canEdit = computed(() => props.canSubmit && !isSubmitting.value && !submitted.value)
const currentQuestion = computed(() => props.questionnaire.questions[currentIndex.value] || null)
const isLastQuestion = computed(() => currentIndex.value >= props.questionnaire.questions.length - 1)
const uiText = computed(() => ({
  other: props.questionnaire.uiText?.other || t('tools.questionnaire.other'),
  answerTitle: props.questionnaire.uiText?.answerTitle || t('tools.questionnaire.answerTitle'),
  questionFallback: props.questionnaire.uiText?.questionFallback || t('tools.questionnaire.questionFallback'),
  unanswered: props.questionnaire.uiText?.unanswered || t('tools.questionnaire.unanswered'),
  unselected: props.questionnaire.uiText?.unselected || t('tools.questionnaire.unselected'),
  answerSeparator: props.questionnaire.uiText?.answerSeparator || t('tools.questionnaire.answerSeparator'),
  listSeparator: props.questionnaire.uiText?.listSeparator || t('tools.questionnaire.listSeparator'),
}))
const progress = computed(() => {
  const count = props.questionnaire.questions.length || 1
  return Math.round(((currentIndex.value + 1) / count) * 100)
})

const singleValue = computed(() => {
  if (currentQuestion.value?.type !== 'single_choice') return ''
  return draft.value[currentQuestion.value.id]?.value || ''
})
const multiValues = computed(() => {
  if (currentQuestion.value?.type !== 'multi_choice') return []
  return draft.value[currentQuestion.value.id]?.values || []
})
const textValue = computed({
  get() {
    if (currentQuestion.value?.type !== 'free_text') return ''
    return draft.value[currentQuestion.value.id] || ''
  },
  set(value) {
    if (currentQuestion.value?.type !== 'free_text') return
    draft.value[currentQuestion.value.id] = value
  },
})
const otherText = computed({
  get() {
    const question = currentQuestion.value
    if (!question || question.type === 'free_text') return ''
    return draft.value[question.id]?.otherText || ''
  },
  set(value) {
    const question = currentQuestion.value
    if (!question || question.type === 'free_text') return
    draft.value[question.id] = {
      ...(draft.value[question.id] || {}),
      otherText: value,
    }
  },
})
const showOtherInput = computed(() => {
  const question = currentQuestion.value
  if (!question?.allowOther) return false
  if (question.type === 'single_choice') return singleValue.value === otherValue
  if (question.type === 'multi_choice') return multiValues.value.includes(otherValue)
  return false
})

function setSingleValue(value) {
  if (!canEdit.value || !currentQuestion.value) return
  draft.value[currentQuestion.value.id] = {
    ...(draft.value[currentQuestion.value.id] || {}),
    value,
  }
}

function toggleMultiValue(value) {
  if (!canEdit.value || !currentQuestion.value) return
  const questionId = currentQuestion.value.id
  const existing = draft.value[questionId]?.values || []
  const values = existing.includes(value)
    ? existing.filter((item) => item !== value)
    : [...existing, value]
  draft.value[questionId] = {
    ...(draft.value[questionId] || {}),
    values,
  }
}

function goBack() {
  currentIndex.value = Math.max(0, currentIndex.value - 1)
}

function handlePrimary() {
  if (!isLastQuestion.value) {
    currentIndex.value = Math.min(props.questionnaire.questions.length - 1, currentIndex.value + 1)
    return
  }
  submit()
}

async function submit() {
  if (!props.canSubmit || isSubmitting.value || submitted.value) return
  isSubmitting.value = true
  try {
    const submission = buildQuestionnaireSubmission(
      props.questionnaire,
      draft.value,
      'submitted',
      uiText.value
    )
    submittedResponse.value = {
      tag: props.questionnaire.tag,
      questionnaireId: props.questionnaire.id,
      status: 'submitted',
      answers: submission.answers,
      uiText: uiText.value,
    }
    emit('submit', submission)
  } finally {
    isSubmitting.value = false
  }
}
</script>
