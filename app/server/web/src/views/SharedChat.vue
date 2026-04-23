<template>
  <div class="flex h-screen w-full flex-col bg-background dark:bg-[rgba(5,5,6,1)]">
    <!-- Header -->
    <div class="sticky top-0 z-10 flex flex-none flex-wrap items-center justify-between gap-3 border-b border-border/55 bg-background/85 px-4 py-2.5 backdrop-blur-md supports-[backdrop-filter]:bg-background/60 dark:bg-[rgba(5,5,6,0.96)]">
      <div class="flex min-w-0 items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/20">
          <Share2 class="h-4 w-4" />
        </div>
        <div class="min-w-0">
          <h1 class="truncate text-[14px] font-semibold tracking-tight text-foreground">
            {{ t('chat.sharedChat') }}
          </h1>
          <p class="truncate text-[11px] text-muted-foreground">
            {{ t('chat.sharedBanner') }}
          </p>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <TooltipProvider>
          <div class="flex h-9 items-center rounded-full border border-border/80 bg-muted/50 p-1 shadow-inner dark:bg-[rgba(4,4,5,0.92)]">
            <Tooltip>
              <TooltipTrigger as-child>
                <button
                  type="button"
                  class="flex h-7 w-7 items-center justify-center rounded-full transition-all"
                  :class="displayMode === CHAT_DISPLAY_MODES.EXECUTION ? 'bg-foreground/10 text-foreground shadow-sm ring-1 ring-border/80 backdrop-blur-sm' : 'text-muted-foreground hover:bg-background/80 hover:text-foreground dark:hover:bg-[rgba(10,10,12,0.96)]'"
                  @click="setDisplayMode(CHAT_DISPLAY_MODES.EXECUTION)"
                >
                  <List class="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('chat.executionFlow') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <button
                  type="button"
                  class="flex h-7 w-7 items-center justify-center rounded-full transition-all"
                  :class="displayMode === CHAT_DISPLAY_MODES.DELIVERY ? 'bg-foreground/10 text-foreground shadow-sm ring-1 ring-border/80 backdrop-blur-sm' : 'text-muted-foreground hover:bg-background/80 hover:text-foreground dark:hover:bg-[rgba(10,10,12,0.96)]'"
                  @click="setDisplayMode(CHAT_DISPLAY_MODES.DELIVERY)"
                >
                  <FileText class="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('chat.deliveryFlow') }}</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </TooltipProvider>
      </div>
    </div>

    <!-- Body -->
    <div class="relative flex-1 overflow-hidden bg-muted/5 dark:bg-[rgba(5,5,6,1)]">
      <div class="h-full overflow-y-auto p-4 sm:p-6 scroll-smooth">
        <div v-if="loading" class="flex h-full flex-col items-center justify-center">
          <Loader class="h-8 w-8 animate-spin text-primary" />
          <p class="mt-4 text-muted-foreground">{{ t('common.loading') || 'Loading...' }}</p>
        </div>

        <div v-else-if="error" class="flex h-full flex-col items-center justify-center">
          <AlertCircle class="mb-4 h-12 w-12 text-destructive" />
          <h3 class="text-lg font-semibold">{{ t('common.error') || 'Error' }}</h3>
          <p class="mt-2 text-muted-foreground">{{ error }}</p>
        </div>

        <div v-else-if="!normalizedMessages || normalizedMessages.length === 0" class="flex h-full flex-col items-center justify-center">
          <p class="text-muted-foreground">{{ t('chat.noMessages') || 'No messages found' }}</p>
        </div>

        <div v-else class="mx-auto w-full max-w-4xl pb-8">
          <template v-for="item in renderDisplayItems" :key="item.id">
            <MessageRenderer
              v-if="item.type === 'message'"
              :message="item.message"
              :messages="item.renderMessages"
              :message-index="item.messageIndex"
              :readonly="true"
              :hide-assistant-avatar="item.hideAssistantAvatar"
              @download-file="downloadFile"
            />
            <div v-else-if="item.type === 'section_marker'" class="px-4 py-2">
              <div class="flex items-center gap-4 text-[11px] text-muted-foreground/80">
                <div class="h-px flex-1 bg-border/70" />
                <span>{{ item.label }}</span>
                <div class="h-px flex-1 bg-border/70" />
              </div>
            </div>
            <DeliveryCollapsedGroup
              v-else
              :group="item"
              :all-messages="normalizedMessages"
              :open="isGroupOpen(item.id)"
              :is-loading="false"
              @toggle="toggleGroup(item)"
              @download-file="downloadFile"
            />
          </template>

          <div class="mt-8 flex items-center justify-center text-[11px] text-muted-foreground/60">
            {{ t('chat.sharedFooter') }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'SharedChat' })

import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Share2, Loader, AlertCircle, List, FileText } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from 'vue-sonner'
import { useLanguage } from '@/utils/i18n.js'
import { chatAPI } from '@/api/chat.js'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import DeliveryCollapsedGroup from '@/components/chat/DeliveryCollapsedGroup.vue'
import {
  CHAT_DISPLAY_MODES,
  buildDeliveryDisplayItems,
  buildExecutionDisplayItems,
  normalizeChatMessages
} from '@/utils/chatDisplayItems.js'
import { getMessageLabel } from '@/utils/messageLabels'

const route = useRoute()
const { t } = useLanguage()

const DISPLAY_MODE_STORAGE_KEY = 'sharedChatDisplayModePreference'

const messages = ref([])
const loading = ref(true)
const error = ref('')
const displayMode = ref(CHAT_DISPLAY_MODES.EXECUTION)
const expandedGroupIds = ref(new Set())

const normalizedMessages = computed(() => normalizeChatMessages(messages.value))

const displayItems = computed(() => {
  if (displayMode.value === CHAT_DISPLAY_MODES.DELIVERY) {
    return buildDeliveryDisplayItems(normalizedMessages.value, { isLoading: false }).items
  }
  return buildExecutionDisplayItems(normalizedMessages.value).items
})

const isGroupOpen = (groupId) => expandedGroupIds.value.has(groupId)

const toggleGroup = (item) => {
  const next = new Set(expandedGroupIds.value)
  if (next.has(item.id)) {
    next.delete(item.id)
  } else {
    next.add(item.id)
  }
  expandedGroupIds.value = next
}

const renderDisplayItems = computed(() => {
  if (displayMode.value !== CHAT_DISPLAY_MODES.DELIVERY) {
    return displayItems.value
  }

  let shouldShowAssistantAvatarForNextAssistant = true
  const rendered = []

  displayItems.value.forEach((item, index) => {
    const normalizedItem = (() => {
      if (item.type !== 'message') return item
      if (item.message?.role === 'user') {
        shouldShowAssistantAvatarForNextAssistant = true
        return item
      }
      if (item.message?.role !== 'assistant') return item
      if (shouldShowAssistantAvatarForNextAssistant) {
        shouldShowAssistantAvatarForNextAssistant = false
        return { ...item, hideAssistantAvatar: false }
      }
      return { ...item, hideAssistantAvatar: true }
    })()

    rendered.push(normalizedItem)

    if ((item.type !== 'tool_group' && item.type !== 'turn_summary') || !isGroupOpen(item.id)) {
      return
    }

    const nextItem = displayItems.value[index + 1]
    if (nextItem?.type !== 'message') return

    const nextRole = nextItem.message?.role
    const label = item.type === 'turn_summary' && nextRole === 'assistant'
      ? t('chat.deliveryFinalMessage')
      : nextRole === 'user'
        ? t('chat.deliveryNextRequest')
        : getMessageLabel({
            role: nextRole,
            type: nextItem.message?.message_type || nextItem.message?.type,
            toolName: nextItem.message?.tool_calls?.[0]?.function?.name,
            t
          }) || t('chat.deliveryProgressMessage')

    rendered.push({
      id: `section-marker:${item.id}:${nextItem.id}`,
      type: 'section_marker',
      label
    })
  })

  return rendered
})

const setDisplayMode = (mode) => {
  displayMode.value = mode
  try {
    window.localStorage.setItem(DISPLAY_MODE_STORAGE_KEY, mode)
  } catch (_) {}
}

const restoreDisplayMode = () => {
  try {
    const saved = window.localStorage.getItem(DISPLAY_MODE_STORAGE_KEY)
    if (saved === CHAT_DISPLAY_MODES.DELIVERY || saved === CHAT_DISPLAY_MODES.EXECUTION) {
      displayMode.value = saved
    }
  } catch (_) {}
}

const downloadFile = (file) => {
  if (!file) {
    toast.error(t('chat.downloadFailed') || 'Download failed')
    return
  }
  const url = typeof file === 'string' ? file : (file.url || file.path)
  if (url) {
    window.open(url, '_blank')
  } else {
    toast.error(t('chat.downloadFailed') || 'Download failed')
  }
}

const loadMessages = async () => {
  const id = route.params.sessionId
  if (!id) {
    error.value = 'Invalid Session ID'
    loading.value = false
    return
  }

  loading.value = true
  try {
    const res = await chatAPI.getSharedConversationMessages(id)
    messages.value = (res && res.messages) ? res.messages : []
  } catch (err) {
    console.error('Failed to load shared conversation:', err)
    error.value = err?.message || 'Failed to load conversation'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  restoreDisplayMode()
  loadMessages()
})
</script>
