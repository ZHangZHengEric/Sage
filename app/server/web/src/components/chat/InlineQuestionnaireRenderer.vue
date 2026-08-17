<template>
  <div class="inline-questionnaire-renderer flex w-full flex-col gap-3">
    <template v-for="part in parts" :key="part.key">
      <component
        v-if="part.type === 'markdown' && part.content.trim()"
        :is="markdownRenderer"
        :content="part.content"
        :compact="compact"
        :message-id="messageId"
      />
      <InlineQuestionnaireCard
        v-else-if="part.type === 'questionnaire'"
        :questionnaire="part.payload"
        :can-submit="canSubmit"
        @submit="handleSubmit"
      />
      <InlineQuestionnaireResponse
        v-else-if="part.type === 'questionnaire_response'"
        :response="part.payload"
      />
      <component
        v-else-if="part.type === 'artifacts'"
        :is="markdownRenderer"
        :content="part.rawText"
        :compact="compact"
        :message-id="messageId"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import MarkdownRendererWithPreview from './MarkdownRendererWithPreview.vue'
import InlineQuestionnaireCard from './InlineQuestionnaireCard.vue'
import InlineQuestionnaireResponse from './InlineQuestionnaireResponse.vue'
import { splitInlineQuestionnaireContent } from '@/utils/inlineQuestionnaire.js'

const props = defineProps({
  content: {
    type: String,
    default: '',
  },
  compact: {
    type: Boolean,
    default: false,
  },
  messageId: {
    type: String,
    default: '',
  },
  canSubmit: {
    type: Boolean,
    default: true,
  },
  withPreview: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['sendMessage'])
const markdownRenderer = computed(() => (
  props.withPreview ? MarkdownRendererWithPreview : MarkdownRenderer
))
const parts = computed(() => (
  splitInlineQuestionnaireContent(props.content, props.messageId || 'assistant_questionnaire')
))

function handleSubmit(submission) {
  emit('sendMessage', submission.agentText, { displayContent: submission.displayText })
}
</script>
