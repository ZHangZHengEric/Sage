<template>
  <div class="px-4 py-1.5">
    <button
      type="button"
      class="group flex w-full items-center gap-4 text-muted-foreground/80 hover:text-foreground transition-colors"
      @click="$emit('toggle')"
    >
      <div class="h-px flex-1 bg-border/70 transition-colors group-hover:bg-border" />
      <div class="flex items-center gap-2 text-[11px] font-medium tracking-wide">
        <span>{{ title }}</span>
        <ChevronDown v-if="open" class="h-4 w-4" />
        <ChevronRight v-else class="h-4 w-4" />
      </div>
      <div class="h-px flex-1 bg-border/70 transition-colors group-hover:bg-border" />
    </button>

    <div v-if="open" class="mt-4 space-y-1">
      <MessageRenderer
        v-for="(message, index) in group.messages"
        :key="message.id || message.message_id || `${group.id}-${index}`"
        :message="message"
        :messages="allMessages"
        :message-index="group.messageIndices[index]"
        :agent-id="agentId"
        :is-loading="isLoading && index === group.messages.length - 1"
        :open-workbench="openWorkbench"
        :extract-workbench-items="false"
        :hide-assistant-avatar="true"
        @download-file="$emit('downloadFile', $event)"
        @sendMessage="$emit('sendMessage', $event)"
        @openSubSession="$emit('openSubSession', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import MessageRenderer from './MessageRenderer.vue'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  group: {
    type: Object,
    required: true
  },
  allMessages: {
    type: Array,
    default: () => []
  },
  open: {
    type: Boolean,
    default: false
  },
  agentId: {
    type: String,
    default: ''
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  openWorkbench: {
    type: Function,
    default: null
  }
})

defineEmits(['toggle', 'downloadFile', 'sendMessage', 'openSubSession'])

const { t } = useLanguage()

const formatDuration = (durationMs) => {
  if (!Number.isFinite(durationMs) || durationMs < 0) return ''
  const totalSeconds = Math.max(1, Math.round(durationMs / 1000))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`
}

const title = computed(() => {
  const action = t(`chat.deliveryAction.${props.group?.actionCode || 'use_tools'}`)
  if (Number.isFinite(props.group?.durationMs)) {
    return `${action} ${formatDuration(props.group.durationMs)}`
  }
  return t('chat.deliveryGroupProcessed', { action })
})
</script>
