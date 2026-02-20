<template>
  <Teleport to="body">
    <div 
      v-if="isOpen" 
      class="fixed inset-0 z-50 flex justify-end bg-black/50 transition-opacity duration-300"
      @click="close"
    >
      <div 
        class="relative w-full max-w-2xl h-full bg-background shadow-2xl transition-transform duration-300 flex flex-col"
        @click.stop
      >
        <!-- Header -->
        <div class="flex items-center justify-between p-4 border-b">
          <div class="flex items-center gap-2">
            <Bot class="w-5 h-5 text-primary" />
            <h2 class="text-lg font-semibold">{{ t('chat.subSessionTitle') }}</h2>
          </div>
          <Button variant="ghost" size="icon" @click="close">
            <X class="w-5 h-5" />
          </Button>
        </div>

        <!-- Messages Area -->
        <div ref="messagesListRef" class="flex-1 overflow-y-auto p-4 custom-scrollbar">
          <div class="space-y-6">
            <MessageRenderer 
              v-for="(message, index) in messages" 
              :key="message.id || index" 
              :message="message"
              :messages="messages" 
              :message-index="index"
              :is-loading="isLoading && index === messages.length - 1"
              @download-file="handleDownloadFile"
              @toolClick="handleToolClick" 
              @openSubSession="handleOpenSubSession"
            />
            
            <!-- Global loading indicator when no messages or waiting for first chunk of response -->
            <div v-if="showLoadingBubble" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
               <LoadingBubble />
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { X, Bot, Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import MessageRenderer from './MessageRenderer.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import { useLanguage } from '@/utils/i18n.js'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  sessionId: {
    type: String,
    default: ''
  },
  messages: {
    type: Array,
    default: () => []
  },
  isLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'downloadFile', 'toolClick', 'openSubSession'])
const { t } = useLanguage()

const close = () => {
  emit('close')
}

const handleDownloadFile = (file) => {
  emit('downloadFile', file)
}

const handleToolClick = (toolCall, result) => {
  emit('toolClick', toolCall, result)
}

const handleOpenSubSession = (sessionId) => {
  emit('openSubSession', sessionId)
}

const showLoadingBubble = computed(() => {
  if (!props.isLoading) return false;
  const msgs = props.messages;
  if (!msgs || msgs.length === 0) return true;
  
  return true;
});

const messagesListRef = ref(null)

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesListRef.value) {
      messagesListRef.value.scrollTop = messagesListRef.value.scrollHeight
    }
  })
}

// Watch for new messages or panel opening to scroll to bottom
watch([() => props.messages, () => props.isOpen, () => props.isLoading], () => {
  if (props.isOpen) {
    scrollToBottom()
  }
}, { deep: true, immediate: true })

</script>

<style scoped>
/* Optional: Add transition classes if not using built-in transition component wrapper */
</style>
