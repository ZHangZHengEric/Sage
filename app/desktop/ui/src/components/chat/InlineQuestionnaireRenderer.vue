<template>
  <div class="inline-questionnaire-renderer flex w-full flex-col gap-3">
    <template v-for="part in parts" :key="part.key">
      <MarkdownRendererWithPreview
        v-if="part.type === 'markdown' && part.content.trim()"
        :content="part.content"
        :compact="compact"
        :message-id="messageId"
        :agent-id="agentId"
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
      <InlineArtifactsCard
        v-else-if="part.type === 'artifacts'"
        :artifacts="part.payload"
        :message-id="messageId"
        :agent-id="agentId"
      />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownRendererWithPreview from './MarkdownRendererWithPreview.vue'
import InlineQuestionnaireCard from './InlineQuestionnaireCard.vue'
import InlineQuestionnaireResponse from './InlineQuestionnaireResponse.vue'
import InlineArtifactsCard from './InlineArtifactsCard.vue'
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
  agentId: {
    type: String,
    default: '',
  },
  canSubmit: {
    type: Boolean,
    default: true,
  },
})

const emit = defineEmits(['sendMessage'])

const parts = computed(() => (
  splitInlineQuestionnaireContent(props.content, props.messageId || 'assistant_questionnaire')
))

function handleSubmit(submission) {
  emit('sendMessage', submission.agentText, { displayContent: submission.displayText })
}
</script>
