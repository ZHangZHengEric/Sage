<template>
  <InlineQuestionnaireCard
    v-if="questionnaire"
    :questionnaire="questionnaire"
    :can-submit="isLatest"
    @submit="handleSubmit"
  />
  <div
    v-else
    class="w-full max-w-md rounded-lg border border-border/70 bg-white/85 p-3 text-sm font-medium text-foreground shadow-sm backdrop-blur-xl dark:bg-card/80"
  >
    {{ t('tools.questionnaire.title') }}
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLanguage } from '@/utils/i18n'
import { questionnaireFromAsyncToolResult } from '@/utils/inlineQuestionnaire.js'
import InlineQuestionnaireCard from './InlineQuestionnaireCard.vue'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true,
  },
  toolResult: {
    type: Object,
    default: null,
  },
  isLatest: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['sendMessage'])
const { t } = useLanguage()
const questionnaire = computed(() => questionnaireFromAsyncToolResult(
  props.toolResult,
  { id: props.toolCall?.id || 'questionnaire_async_q1' }
))

function handleSubmit(submission) {
  emit('sendMessage', submission.agentText, { displayContent: submission.displayText })
}
</script>
