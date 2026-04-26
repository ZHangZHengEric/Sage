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

    <div v-if="open" class="mt-2 space-y-0.5">
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
import { ref, computed, watch, onUnmounted } from 'vue'
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

// 判断当前 group 的工具是否还在执行中：
// 最后一条消息是带 tool_calls 的 assistant 消息（还没有收到 tool result）
const isGroupRunning = computed(() => {
  if (!props.isLoading) return false
  const msgs = props.group?.messages
  if (!msgs?.length) return false
  const lastMsg = msgs[msgs.length - 1]
  return lastMsg?.role === 'assistant' &&
    Array.isArray(lastMsg?.tool_calls) &&
    lastMsg.tool_calls.length > 0
})

const liveElapsedMs = ref(0)
let liveTimer = null

watch(isGroupRunning, (running) => {
  clearInterval(liveTimer)
  liveTimer = null
  if (running && props.group?.startTimestampMs) {
    const tick = () => {
      liveElapsedMs.value = Math.max(0, Date.now() - props.group.startTimestampMs)
    }
    tick()
    liveTimer = setInterval(tick, 1000)
  }
}, { immediate: true })

onUnmounted(() => {
  clearInterval(liveTimer)
})

const title = computed(() => {
  const action = t(`chat.deliveryAction.${props.group?.actionCode || 'use_tools'}`)
  if (isGroupRunning.value) {
    return `${action} ${formatDuration(liveElapsedMs.value)}`
  }
  if (Number.isFinite(props.group?.durationMs)) {
    return `${action} ${formatDuration(props.group.durationMs)}`
  }
  return t('chat.deliveryGroupProcessed', { action })
})
</script>
