<template>
  <div class="space-y-3 rounded-md bg-muted/30 p-3">
    <div class="flex items-center gap-2 text-sm font-medium text-green-600 dark:text-green-400">
      <CheckCircle2 class="h-4 w-4" />
      <span>{{ statusText }}</span>
    </div>
    <div class="space-y-3">
      <div
        v-for="(answer, index) in response.answers"
        :key="answer.question_id || answer.question || index"
        class="space-y-1"
      >
        <div class="text-sm font-medium leading-6 text-foreground">
          {{ answer.question || answer.question_id }}
        </div>
        <div class="text-sm leading-6 text-muted-foreground">
          {{ displayValueForAnswer(answer) }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CheckCircle2 } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n'
import { displayValueForAnswer } from '@/utils/inlineQuestionnaire.js'

const props = defineProps({
  response: {
    type: Object,
    required: true,
  },
})

const { t } = useLanguage()

const statusText = computed(() => (
  props.response.status === 'timeout_default'
    ? t('tools.questionnaire.autoSubmitted')
    : t('tools.questionnaire.submitted')
))
</script>
