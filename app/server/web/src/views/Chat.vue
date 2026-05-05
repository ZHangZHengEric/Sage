<template>
  <div class="flex flex-col h-full bg-background dark:bg-[rgba(5,5,6,1)]">
    <div class="sticky top-0 z-10 flex min-h-[60px] flex-none flex-wrap items-center gap-2 bg-background/80 px-3 py-2 backdrop-blur-md supports-[backdrop-filter]:bg-background/60 dark:bg-[rgba(5,5,6,0.96)] sm:px-4 md:justify-end">
      <div class="flex w-full items-center justify-between gap-2 md:w-auto md:justify-end">
        <Select :model-value="selectedAgentId" @update:model-value="handleAgentChange">
          <SelectTrigger class="h-9 w-[148px] min-w-0 rounded-full border-muted-foreground/20 bg-muted/50 px-2.5 transition-colors hover:bg-muted/80 focus:ring-1 focus:ring-primary/20 dark:bg-[rgba(4,4,5,0.92)] dark:hover:bg-[rgba(10,10,12,0.96)] sm:w-[172px]">
            <div class="flex items-center gap-2 w-full">
              <div class="w-5 h-5 rounded-full overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/10">
                <img
                  v-if="selectedAgent"
                  :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(selectedAgent.id)}`"
                  :alt="selectedAgent.name"
                  class="w-full h-full object-cover"
                />
                <Bot v-else class="w-full h-full p-0.5 text-primary/60" />
              </div>
              <span class="text-sm font-medium text-foreground truncate flex-1">
                {{ selectedAgent?.name || t('chat.selectAgent') || '选择智能体' }}
              </span>
            </div>
          </SelectTrigger>
          <SelectContent class="w-[240px] p-2">
            <div class="grid grid-cols-4 gap-1.5">
              <RadixSelectItem
                v-for="agent in (agents || [])"
                :key="agent.id"
                :value="agent.id"
                :text-value="agent.name"
                class="relative flex min-h-[4.25rem] w-full cursor-pointer select-none items-center justify-center rounded-lg p-1.5 outline-none transition-colors data-[highlighted]:bg-muted/80 data-[state=checked]:bg-primary/10 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
              >
                <RadixSelectItemText as="div" class="flex w-full flex-col items-center gap-1">
                  <div class="relative w-9 h-9 rounded-lg overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5">
                    <img
                      :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(agent.id)}`"
                      :alt="agent.name"
                      class="w-full h-full object-cover"
                    />
                  </div>
                  <div class="flex items-center justify-center w-full px-0.5">
                    <span class="block max-w-full truncate text-[10px] font-medium text-foreground text-center leading-none">
                      {{ agent.name }}
                    </span>
                  </div>
                </RadixSelectItemText>
                <span class="absolute top-1.5 right-1.5 flex h-3 w-3 items-center justify-center">
                  <RadixSelectItemIndicator>
                    <span class="h-1.5 w-1.5 rounded-full bg-green-500" />
                  </RadixSelectItemIndicator>
                </span>
              </RadixSelectItem>
            </div>
          </SelectContent>
        </Select>

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

        <div class="mx-1 hidden h-4 w-[1px] bg-border sm:block"></div>

        <TooltipProvider>
          <div class="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80 dark:hover:bg-[rgba(10,10,12,0.96)]" @click="toggleWorkbench">
                  <Monitor class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workbench.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80 dark:hover:bg-[rgba(10,10,12,0.96)]" @click="toggleWorkspace">
                  <FolderOpen class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workspace.title') }}</p>
              </TooltipContent>
            </Tooltip>

          </div>
        </TooltipProvider>
      </div>
    </div>

    <div class="relative flex-1 overflow-hidden flex flex-row pb-6">
      <div
        class="flex-1 flex flex-col min-w-0 bg-muted/5 relative transition-all duration-200 dark:bg-[rgba(5,5,6,1)]"
        :class="{ 'mr-0': !anyPanelOpen }"
      >
        <div ref="messagesListRef" class="flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth" @scroll="handleScroll">
          <div
            v-if="overlayAbilityPanel"
            class="flex flex-col items-start text-left p-4 sm:p-6 text-muted-foreground animate-in fade-in zoom-in duration-500"
          >
            <AbilityPanel
              :items="abilityItems"
              :loading="abilityLoading"
              :error="abilityError"
              @close="closeAbilityPanel"
              @retry="retryAbilityFetch"
              @refresh="retryAbilityFetch"
              @select="onAbilityCardClick"
            />
          </div>

          <template v-else>
            <AbilityPanel
              v-if="showAbilityPanel"
              :items="abilityItems"
              :loading="abilityLoading"
              :error="abilityError"
              @close="closeAbilityPanel"
              @retry="retryAbilityFetch"
              @refresh="retryAbilityFetch"
              @select="onAbilityCardClick"
            />

            <div v-if="currentSessionId" class="mx-auto w-full max-w-4xl">
              <SessionGoalCard
                :goal="currentGoal"
                :goal-transition="currentGoalTransition"
                :busy="isGoalMutating"
                :can-edit="!!currentGoal || normalizedMessages.length > 0"
                @save-goal="saveSessionGoal"
                @clear-goal="clearSessionGoal"
                @complete-goal="completeSessionGoal"
              />
            </div>

            <div
              v-if="!filteredMessages || filteredMessages.length === 0"
              class="flex flex-col items-center justify-center text-center p-8 h-full text-muted-foreground animate-in fade-in zoom-in duration-500"
            >
              <div class="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-6 shadow-sm overflow-hidden dark:bg-[rgba(10,10,12,0.96)]">
                <img
                  v-if="selectedAgent"
                  :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(selectedAgent.id)}`"
                  :alt="selectedAgent.name"
                  class="w-full h-full object-cover"
                />
                <Bot v-else :size="32" class="opacity-80 text-primary" />
              </div>
              <h3 class="mb-3 text-xl font-semibold text-foreground">{{ t('chat.emptyTitle') }}</h3>
              <p class="mb-8 text-sm max-w-md mx-auto leading-relaxed text-muted-foreground/80">{{ t('chat.emptyDesc') }}</p>
            </div>

            <div v-else class="pb-8 max-w-4xl mx-auto w-full">
              <template v-for="item in renderDisplayItems" :key="item.id">
                <MessageRenderer
                  v-if="item.type === 'message'"
                  :message="item.message"
                  :messages="item.renderMessages"
                  :message-index="item.messageIndex"
                  :agent-id="selectedAgentId"
                  :is-loading="isCurrentSessionLoading && item.messageIndex === normalizedMessages.length - 1"
                  :open-workbench="openWorkbench"
                  :hide-assistant-avatar="item.hideAssistantAvatar"
                  :editable-user-message-id="editableUserMessageId"
                  :editing-user-message-id="editingUserMessageId"
                  @download-file="downloadWorkspaceFile"
                  @sendMessage="handleSendMessage"
                  @startEditUserMessage="startEditUserMessage"
                  @cancelEditUserMessage="cancelEditUserMessage"
                  @submitEditUserMessage="submitEditUserMessage"
                  @openSubSession="handleOpenSubSession"
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
                  :agent-id="selectedAgentId"
                  :is-loading="isCurrentSessionLoading"
                  :open-workbench="openWorkbench"
                  @toggle="toggleGroup(item)"
                  @download-file="downloadWorkspaceFile"
                  @sendMessage="handleSendMessage"
                  @openSubSession="handleOpenSubSession"
                />
              </template>

              <div v-if="showLoadingBubble" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
                <LoadingBubble />
              </div>
            </div>
          </template>
          <div ref="messagesEndRef" />
        </div>

        <div class="flex-none p-4 bg-background dark:bg-[rgba(5,5,6,1)]" v-if="selectedAgent">
          <div class="w-full max-w-[800px] mx-auto">
            <div class="flex justify-start items-start pb-2 pr-1">
              <Button
                v-if="showAbilityButton"
                variant="ghost"
                size="sm"
                class="h-8 px-3 gap-2 text-primary hover:bg-primary/10"
                :disabled="isCurrentSessionLoading || abilityLoading"
                :title="t('quickHelp.tooltip')"
                @click="handleClickAbilityButton"
              >
                <Sparkles class="h-4 w-4" />
                {{ t('quickHelp.cta') }}
              </Button>
            </div>
            <MessageInput
              ref="messageInputRef"
              :agent-id="selectedAgentId"
              :is-loading="isCurrentSessionLoading"
              :preset-text="abilityPresetInput"
              :session-id="currentSessionId"
              :selected-agent="selectedAgent"
              :config="config"
              :delivery-context-messages="recentDeliveryContextMessages"
              @send-message="handleSendMessageWithAbilityClear"
              @config-change="updateConfig"
              @stop-generation="stopGeneration"
            />
          </div>
        </div>
      </div>

      <SubSessionPanel
        :is-open="!!activeSubSessionId"
        :session-id="activeSubSessionId"
        :messages="subSessionMessages"
        :is-loading="isLoading"
        :agent-id="selectedAgentId"
        @close="handleCloseSubSession"
        @download-file="downloadWorkspaceFile"
        @openSubSession="handleOpenSubSession"
      />

      <Transition name="panel">
        <WorkspacePanel
          v-if="panelStore.showWorkspace"
          ref="workspacePanelRef"
          :workspace-files="workspaceFiles"
          :is-loading="isWorkspaceLoading"
          :agent-id="selectedAgentId"
          :session-id="currentSessionId"
          @download-file="downloadFile"
          @delete-file="handleDeleteFile"
          @quote-path="handleQuotePath"
          @upload-files="handleUploadFiles"
          @refresh="refreshWorkspace"
          @close="panelStore.closeAll()"
        />
      </Transition>

      <Transition name="panel">
        <WorkbenchPreview
          v-if="panelStore.showWorkbench && currentSessionId"
          :key="`workbench-${currentSessionId}`"
          :messages="filteredMessages"
          :session-id="currentSessionId"
          :is-loading="isCurrentSessionLoading"
          @close="panelStore.closeAll()"
          @quote-path="handleQuotePath"
        />
      </Transition>

    </div>
    <AppConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
defineOptions({ name: 'Chat' })

import { computed, onMounted, ref, watch } from 'vue'
import { Bot, FolderOpen, Monitor, List, FileText, Sparkles } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import DeliveryCollapsedGroup from '@/components/chat/DeliveryCollapsedGroup.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'
import WorkbenchPreview from '@/components/chat/WorkbenchPreview.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import SubSessionPanel from '@/components/chat/SubSessionPanel.vue'
import AbilityPanel from '@/components/chat/AbilityPanel.vue'
import SessionGoalCard from '@/components/chat/SessionGoalCard.vue'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectTrigger
} from '@/components/ui/select'
import {
  SelectItem as RadixSelectItem,
  SelectItemIndicator as RadixSelectItemIndicator,
  SelectItemText as RadixSelectItemText,
} from 'radix-vue'
import { useChatPage } from '@/composables/chat/useChatPage.js'
import { useWorkbenchStore } from '@/stores/workbench'
import { usePanelStore } from '@/stores/panel'
import { getMessageLabel } from '@/utils/messageLabels'
import { taskAPI } from '@/api/task.js'
import { toast } from 'vue-sonner'
import {
  CHAT_DISPLAY_MODES,
  buildDeliveryDisplayItems,
  buildExecutionDisplayItems,
  normalizeChatMessages
} from '@/utils/chatDisplayItems.js'
import { isTokenUsageMessage } from '@/utils/messageLabels.js'

const props = defineProps({
  selectedConversation: {
    type: Object,
    default: null
  },
  chatResetToken: {
    type: Number,
    default: 0
  }
})

const {
  t,
  agents,
  selectedAgent,
  selectedAgentId,
  config,
  showLoadingBubble,
  filteredMessages,
  currentGoal,
  currentGoalTransition,
  isGoalMutating,
  isLoading,
  isCurrentSessionLoading,
  currentSessionId,
  messagesListRef,
  messagesEndRef,
  handleAgentChange,
  handleScroll,
  handleSendMessage,
  togglePanel,
  openWorkbench,
  stopGeneration,
  activeSubSessionId,
  subSessionMessages,
  handleCloseSubSession,
  handleOpenSubSession,
  downloadWorkspaceFile,
  workspaceFiles,
  isWorkspaceLoading,
  downloadFile,
  deleteFile,
  refreshWorkspace,
  updateConfig,
  abilityItems,
  abilityLoading,
  abilityError,
  showAbilityPanel,
  abilityPresetInput,
  showAbilityButton,
  hasUsedAbilityEntryInSession,
  openAbilityPanel,
  closeAbilityPanel,
  retryAbilityFetch,
  onAbilityCardClick,
  submitEditedLastUserMessage,
  saveSessionGoal,
  clearSessionGoal,
  completeSessionGoal
} = useChatPage(props)

const workbenchStore = useWorkbenchStore()
const panelStore = usePanelStore()
const displayMode = ref(CHAT_DISPLAY_MODES.EXECUTION)
const expandedGroupIds = ref(new Set())
const DISPLAY_MODE_STORAGE_KEY = 'chatDisplayModePreference'
const messageInputRef = ref(null)
const workspacePanelRef = ref(null)
const confirmDialogRef = ref(null)
const editingUserMessageId = ref(null)

const normalizedMessages = computed(() => normalizeChatMessages(filteredMessages.value))
const editableUserMessageId = computed(() => {
  for (let index = normalizedMessages.value.length - 1; index >= 0; index -= 1) {
    const message = normalizedMessages.value[index]
    if (message?.role === 'user' && (message.message_id || message.id)) {
      return message.message_id || message.id
    }
  }
  return null
})

const getMessageTextForInputOptimization = (message) => {
  const content = message?.content
  if (typeof content === 'string') return content.trim()
  if (!Array.isArray(content)) return ''

  return content
    .filter(item => item?.type === 'text' && typeof item.text === 'string')
    .map(item => item.text.trim())
    .filter(Boolean)
    .join('\n')
    .trim()
}

const getDeliveryActionLabel = (actionCode) => (
  t(`chat.deliveryAction.${actionCode}`) || t('chat.deliveryProgressMessage')
)

const recentDeliveryContextMessages = computed(() => {
  const userMessageIndices = normalizedMessages.value
    .map((message, index) => (message?.role === 'user' ? index : -1))
    .filter(index => index >= 0)

  const startIndex = userMessageIndices.length > 2 ? userMessageIndices[userMessageIndices.length - 2] : 0
  const recentMessages = normalizedMessages.value.slice(startIndex)
  const deliveryItems = buildDeliveryDisplayItems(recentMessages, {
    isLoading: isCurrentSessionLoading.value
  }).items

  return deliveryItems.flatMap((item) => {
    if (item.type === 'message') {
      const message = item.message
      if (!message || isTokenUsageMessage(message)) {
        return []
      }

      const content = getMessageTextForInputOptimization(message)
      if (!content) return []
      return [{ role: message.role || 'assistant', content }]
    }

    if (item.type === 'tool_group' || item.type === 'turn_summary') {
      return [{
        role: 'assistant',
        content: getDeliveryActionLabel(item.actionCode)
      }]
    }

    return []
  })
})

const displayItems = computed(() => {
  if (displayMode.value === CHAT_DISPLAY_MODES.DELIVERY) {
    return buildDeliveryDisplayItems(normalizedMessages.value, {
      isLoading: isCurrentSessionLoading.value
    }).items
  }
  return buildExecutionDisplayItems(normalizedMessages.value).items
})

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
    if (nextItem?.type !== 'message') {
      return
    }

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

const startEditUserMessage = (message) => {
  const messageId = message?.message_id || message?.id
  if (!messageId || messageId !== editableUserMessageId.value) return
  editingUserMessageId.value = messageId
}

const cancelEditUserMessage = () => {
  editingUserMessageId.value = null
}

const submitEditUserMessage = async (content) => {
  const previousEditingMessageId = editingUserMessageId.value
  editingUserMessageId.value = null
  const success = await submitEditedLastUserMessage(content)
  if (success) {
    return
  }
  editingUserMessageId.value = previousEditingMessageId
}

const syncExpandedGroups = () => {
  if (displayMode.value !== CHAT_DISPLAY_MODES.DELIVERY) {
    if (expandedGroupIds.value.size > 0) {
      expandedGroupIds.value = new Set()
    }
    return
  }

  const nextExpanded = new Set()

  if (isCurrentSessionLoading.value) {
    const lastDisplayItem = displayItems.value[displayItems.value.length - 1]
    if (lastDisplayItem?.type === 'tool_group') {
      nextExpanded.add(lastDisplayItem.id)
    }
  } else {
    displayItems.value.forEach((item) => {
      if (item.type === 'turn_summary' && expandedGroupIds.value.has(item.id)) {
        nextExpanded.add(item.id)
      }
    })
  }

  const currentIds = [...expandedGroupIds.value]
  const nextIds = [...nextExpanded]
  const changed = currentIds.length !== nextIds.length || currentIds.some((id, index) => id !== nextIds[index])
  if (changed) {
    expandedGroupIds.value = nextExpanded
  }
}

const setDisplayMode = (mode) => {
  if (displayMode.value === mode) return
  displayMode.value = mode
}

const isGroupOpen = (groupId) => expandedGroupIds.value.has(groupId)

const toggleGroup = (item) => {
  const nextExpanded = new Set(expandedGroupIds.value)
  const isOpen = nextExpanded.has(item.id)

  if (item.type === 'tool_group' && isCurrentSessionLoading.value) {
    nextExpanded.clear()
    if (!isOpen) {
      nextExpanded.add(item.id)
    }
  } else if (isOpen) {
    nextExpanded.delete(item.id)
  } else {
    nextExpanded.add(item.id)
  }

  expandedGroupIds.value = nextExpanded
}

const toggleWorkbench = () => {
  togglePanel('workbench')
}

const toggleWorkspace = () => {
  togglePanel('workspace')
}

const anyPanelOpen = computed(() => (
  panelStore.showWorkspace || panelStore.showWorkbench
))

const handleClickAbilityButton = () => {
  if (!showAbilityPanel.value) {
    openAbilityPanel()
  }
  showAbilityButton.value = false
  hasUsedAbilityEntryInSession.value = true
}

const handleSendMessageWithAbilityClear = (content, options) => {
  handleSendMessage(content, options)
  abilityPresetInput.value = ''
}

const handleDeleteFile = async (item) => {
  const confirmed = await confirmDialogRef.value?.confirm(
    t('common.confirmDelete') || '确定要删除此文件吗？',
    { title: t('common.confirm') || '确认' }
  )
  if (!confirmed) return
  await deleteFile(item)
}

const handleQuotePath = (path) => {
  const pathToInsert = `\`{workspace_root}/${path}\``
  if (messageInputRef.value) {
    messageInputRef.value.appendInputValue(pathToInsert)
  }
}

const handleUploadFiles = async (files) => {
  if (!selectedAgentId.value || !Array.isArray(files) || files.length === 0) return

  try {
    workspacePanelRef.value?.setUploadStatus('准备上传...', 0)
    let uploadedCount = 0
    const totalFiles = files.length

    for (const fileInfo of files) {
      const { file, relativePath } = fileInfo
      workspacePanelRef.value?.setUploadStatus(
        `上传 ${relativePath}...`,
        Math.round((uploadedCount / totalFiles) * 100)
      )
      const targetPath = relativePath.includes('/')
        ? relativePath.substring(0, relativePath.lastIndexOf('/'))
        : ''
      await taskAPI.uploadWorkspaceFile(selectedAgentId.value, file, targetPath)
      uploadedCount += 1
    }

    workspacePanelRef.value?.setUploadStatus('上传完成', 100)
    toast.success(`成功上传 ${uploadedCount} 个文件`)
    setTimeout(() => {
      workspacePanelRef.value?.setUploadStatus('')
      refreshWorkspace()
    }, 1000)
  } catch (error) {
    console.error('上传文件出错:', error)
    workspacePanelRef.value?.setUploadStatus('')
    toast.error(`上传失败: ${error.message}`)
  }
}

const overlayAbilityPanel = computed(() => {
  const noMessages = !filteredMessages.value || filteredMessages.value.length === 0
  return showAbilityPanel.value && noMessages
})

watch(() => currentSessionId.value, (id) => {
  if (id) workbenchStore.setSessionId(id)
}, { immediate: true })

watch(
  () => [panelStore.showWorkspace, selectedAgentId.value, currentSessionId.value],
  ([showWorkspace]) => {
    if (!showWorkspace) return
    refreshWorkspace()
  },
  { immediate: true }
)

onMounted(() => {
  try {
    const savedMode = localStorage.getItem(DISPLAY_MODE_STORAGE_KEY)
    if (savedMode === CHAT_DISPLAY_MODES.EXECUTION || savedMode === CHAT_DISPLAY_MODES.DELIVERY) {
      displayMode.value = savedMode
    }
  } catch (error) {
    console.warn('Failed to restore chat display mode preference:', error)
  }
})

watch(displayMode, (mode) => {
  try {
    localStorage.setItem(DISPLAY_MODE_STORAGE_KEY, mode)
  } catch (error) {
    console.warn('Failed to persist chat display mode preference:', error)
  }
})

watch(
  () => [displayMode.value, currentSessionId.value, isCurrentSessionLoading.value, displayItems.value.map(item => item.id).join('|')],
  () => {
    syncExpandedGroups()
  },
  { immediate: true }
)
</script>

<style scoped>
.panel-enter-active,
.panel-leave-active {
  transition: all 0.2s ease;
}

.panel-enter-from,
.panel-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

@media (max-width: 640px) {
  .panel-enter-from,
  .panel-leave-to {
    transform: translateY(12px);
  }
}
</style>
