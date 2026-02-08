<template>
  <div class="h-screen w-full bg-background flex flex-col">

    <!-- Content -->
    <div class="flex-1 overflow-hidden relative bg-muted/5">
      <div class="h-full overflow-y-auto p-4 sm:p-6 scroll-smooth">
        <div v-if="loading" class="flex flex-col items-center justify-center h-full">
          <Loader class="h-8 w-8 animate-spin text-primary" />
          <p class="mt-4 text-muted-foreground">{{ t('common.loading') || 'Loading...' }}</p>
        </div>

        <div v-else-if="error" class="flex flex-col items-center justify-center h-full">
          <AlertCircle class="h-12 w-12 text-destructive mb-4" />
          <h3 class="text-lg font-semibold">{{ t('common.error') || 'Error' }}</h3>
          <p class="text-muted-foreground mt-2">{{ error }}</p>
        </div>

        <div v-else-if="!messages || messages.length === 0" class="flex flex-col items-center justify-center h-full">
          <p class="text-muted-foreground">{{ t('chat.noMessages') || 'No messages found' }}</p>
        </div>

        <div v-else class="pb-8 max-w-4xl mx-auto w-full">
          <MessageRenderer v-for="(message, index) in messages" :key="message.id || index" :message="message"
            :messages="messages" :message-index="index" :readonly="true" @download-file="downloadFile" @tool-click="handleToolClick" />
        </div>
      </div>
    </div>

    <ToolDetailsPanel v-model:open="showToolDetails" :tool-execution="selectedToolExecution"
      :tool-result="toolResult" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Bot, Loader, AlertCircle } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { chatAPI } from '@/api/chat.js'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import ToolDetailsPanel from '@/components/chat/tools/ToolDetailsPanel.vue'
import { toast } from 'vue-sonner'

const route = useRoute()
const { t } = useLanguage()

const conversationId = ref('')
const messages = ref([])
const loading = ref(true)
const error = ref('')

const showToolDetails = ref(false)
const selectedToolExecution = ref(null)
const toolResult = ref(null)

const loadMessages = async () => {
  const id = route.params.sessionId
  if (!id) {
    error.value = 'Invalid Session ID'
    loading.value = false
    return
  }

  conversationId.value = id
  loading.value = true

  try {
    const res = await chatAPI.getSharedConversationMessages(id)
    if (res && res.messages) {
      messages.value = res.messages
    } else {
      messages.value = []
    }
  } catch (err) {
    console.error('Failed to load shared conversation:', err)
    error.value = err.message || 'Failed to load conversation'
  } finally {
    loading.value = false
  }
}

const downloadFile = (file) => {
  // Try to download file. Note: This might fail if auth is required for file access.
  // For shared views, we might need a public file endpoint, but for now we attempt direct link.
  if (file && file.path) {
    window.open(file.path, '_blank')
  } else {
    toast.error(t('chat.downloadFailed') || 'Download failed')
  }
}

const handleToolClick = (toolExecution, result) => {
  selectedToolExecution.value = toolExecution
  toolResult.value = result
  showToolDetails.value = true
}

onMounted(() => {
  loadMessages()
})
</script>
