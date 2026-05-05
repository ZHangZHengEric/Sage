<template>
  <div class="flex h-full flex-col bg-background">
    <div class="sticky top-0 z-10 flex min-h-[60px] flex-none flex-wrap items-center gap-2 border-b border-border/40 bg-background/80 px-3 py-2 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60 sm:px-4">
      <div class="hidden h-full min-w-0 flex-1 md:block" />

      <div class="flex w-full items-center justify-between gap-2 md:w-auto md:justify-end">
        <!-- Agent 选择器 - 紧凑网格布局 -->
        <Select :model-value="selectedAgentId" @update:model-value="handleAgentChange">
          <SelectTrigger class="h-9 w-[148px] min-w-0 rounded-full border border-border/80 bg-background/88 px-3 shadow-[0_10px_30px_rgba(15,23,42,0.08),inset_0_1px_0_rgba(255,255,255,0.22)] transition-all hover:border-border hover:bg-background focus:ring-2 focus:ring-primary/20 sm:w-[172px] dark:border-white/12 dark:bg-[rgba(4,4,5,0.92)] dark:shadow-[0_12px_32px_rgba(0,0,0,0.42),inset_0_1px_0_rgba(255,255,255,0.04)] dark:hover:border-white/18 dark:hover:bg-[rgba(10,10,12,0.96)]">
            <div class="flex items-center gap-2 w-full">
              <!-- Agent 头像 -->
              <div class="w-5 h-5 rounded-full overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/15">
                <img
                  v-if="selectedAgent"
                  :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(selectedAgent.id)}`"
                  :alt="selectedAgent.name"
                  class="w-full h-full object-cover"
                />
                <Bot v-else class="w-full h-full p-0.5 text-primary/60" />
              </div>
              <!-- Agent 名称 -->
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
                  <!-- Agent 头像 -->
                  <div class="relative w-9 h-9 rounded-lg overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5">
                    <img
                      :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(agent.id)}`"
                      :alt="agent.name"
                      class="w-full h-full object-cover"
                    />
                  </div>
                  <!-- Agent 名称 -->
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
          <div class="flex h-9 items-center rounded-full border border-border/75 bg-background/88 p-1 shadow-[0_10px_28px_rgba(15,23,42,0.08),inset_0_1px_0_rgba(255,255,255,0.18)] dark:border-white/12 dark:bg-[rgba(4,4,5,0.92)] dark:shadow-[0_12px_30px_rgba(0,0,0,0.38),inset_0_1px_0_rgba(255,255,255,0.04)]">
            <Tooltip>
              <TooltipTrigger as-child>
                <button
                  type="button"
                  class="flex h-7 w-7 items-center justify-center rounded-full border transition-all"
                  :class="displayMode === CHAT_DISPLAY_MODES.EXECUTION ? 'border-border/80 bg-foreground/10 text-foreground shadow-[0_6px_18px_rgba(15,23,42,0.1)] dark:border-white/10 dark:bg-white/12' : 'border-transparent text-muted-foreground hover:border-border/70 hover:bg-background hover:text-foreground dark:hover:border-white/10 dark:hover:bg-white/8'"
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
                  class="flex h-7 w-7 items-center justify-center rounded-full border transition-all"
                  :class="displayMode === CHAT_DISPLAY_MODES.DELIVERY ? 'border-border/80 bg-foreground/10 text-foreground shadow-[0_6px_18px_rgba(15,23,42,0.1)] dark:border-white/10 dark:bg-white/12' : 'border-transparent text-muted-foreground hover:border-border/70 hover:bg-background hover:text-foreground dark:hover:border-white/10 dark:hover:bg-white/8'"
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

        <div class="mx-0.5 hidden h-5 w-px bg-border/80 dark:bg-white/10 sm:block"></div>

        <TooltipProvider>
          <div class="flex items-center gap-1.5">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 rounded-full border border-transparent bg-background/65 text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] hover:border-border/70 hover:bg-background hover:text-foreground dark:bg-[rgba(4,4,5,0.9)] dark:hover:border-white/10 dark:hover:bg-[rgba(10,10,12,0.98)]" @click="togglePanel('workbench')">
                  <Monitor class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workbench.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 rounded-full border border-transparent bg-background/65 text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] hover:border-border/70 hover:bg-background hover:text-foreground dark:bg-[rgba(4,4,5,0.9)] dark:hover:border-white/10 dark:hover:bg-[rgba(10,10,12,0.98)]" @click="togglePanel('workspace')">
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
    <div class="relative flex flex-1 flex-row overflow-hidden pb-4 dark:bg-[rgba(5,5,6,1)]">
      <!-- 主聊天区域 -->
      <div
        class="flex-1 flex flex-col min-w-0 bg-muted/5 relative transition-all duration-200 dark:bg-[rgba(5,5,6,1)]"
        :class="{ 'mr-0': !anyPanelOpen }"
      >
        <!-- 弹幕叠在聊天区域上方；能力面板打开或用户已发送消息时不渲染弹幕 -->
        <div v-if="!showAbilityPanel && filteredMessages.length === 0" class="absolute top-5 left-0 right-0 h-[25%] min-h-[100px] max-h-[180px] overflow-hidden pointer-events-none z-10">
          <AgentUsageDanmaku :agent-id="selectedAgentId" :hide-for-history="isViewingHistorySession" :closed-by-user="danmakuClosedByUser" :reset-trigger="danmakuResetTrigger" @close="onDanmakuClose" />
        </div>
        <div ref="messagesListRef" class="flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth" @scroll="handleScroll">
          <!-- 覆盖模式：当无消息且能力结果已加载好时，用能力面板直接占据原聊天空态区域 -->
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

          <!-- 非覆盖模式：能力面板在对话区域上方，下面是空态或消息列表 -->
          <template v-else>
            <!-- 能力面板：始终作为对话区域上方的模块（加载中 / 无结果时使用这种模式） -->
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

            <!-- 无消息时：默认显示空态 -->
            <div
              v-if="!filteredMessages || filteredMessages.length === 0"
              class="flex flex-col items-center justify-center text-center p-8 h-full text-muted-foreground animate-in fade-in zoom-in duration-500"
            >
              <div class="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-6 shadow-sm overflow-hidden">
                <img
                  v-if="selectedAgent"
                  :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(selectedAgent.id)}`"
                  :alt="selectedAgent.name"
                  class="w-full h-full object-cover"
                />
                <Bot v-else :size="32" class="opacity-80 text-primary" />
              </div>
              <h3 class="mb-3 text-xl font-semibold text-foreground">{{ t('chat.emptyTitle') }}</h3>
              <p class="mb-8 text-sm max-w-md mx-auto leading-relaxed text-muted-foreground/80">
                {{ t('chat.emptyDesc') }}
              </p>
            </div>

            <!-- 有消息时：正常显示消息列表 -->
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

              <!-- Global loading indicator when等待首个响应块 -->
              <div v-if="showLoadingBubble" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
                <LoadingBubble />
              </div>
            </div>
          </template>
          <div ref="messagesEndRef" />
        </div>

      <div class="flex-none px-4 pt-4 pb-0 bg-background" v-if="selectedAgent">
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
            <GuidanceArea
              v-if="currentSessionId"
              :session-id="currentSessionId"
              :apply-now-handler="applyGuidanceNow"
            />
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

      <!-- 右侧面板区域 -->
      <Transition name="panel">
        <WorkspacePanel
          v-if="showWorkspace"
          ref="workspacePanelRef"
          :workspace-files="workspaceFiles"
          :is-loading="isWorkspaceLoading"
          :agent-id="selectedAgentId"
          @download-file="downloadFile"
          @delete-file="handleDeleteFile"
          @quote-path="handleQuotePath"
          @upload-files="handleUploadFiles"
          @refresh="refreshWorkspace"
          @close="showWorkspace = false"
        />
      </Transition>

      <Transition name="panel">
        <WorkbenchPreview
          v-if="showWorkbench && currentSessionId"
          :key="`workbench-${currentSessionId}`"
          :messages="filteredMessages"
          :session-id="currentSessionId"
          :is-loading="isCurrentSessionLoading"
          @close="showWorkbench = false"
          @quote-path="handleQuotePath"
        />
      </Transition>

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
    </div>

    <!-- 确认对话框 -->
    <AppConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
defineOptions({ name: 'Chat' })
import { computed, onMounted, ref, watch } from 'vue'
import { Bot, FolderOpen, Monitor, Sparkles, List, FileText } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import DeliveryCollapsedGroup from '@/components/chat/DeliveryCollapsedGroup.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import GuidanceArea from '@/components/chat/GuidanceArea.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import SubSessionPanel from '@/components/chat/SubSessionPanel.vue'
import WorkbenchPreview from '@/components/chat/WorkbenchPreview.vue'
import AbilityPanel from '@/components/chat/AbilityPanel.vue'
import AgentUsageDanmaku from '@/components/chat/AgentUsageDanmaku.vue'
import SessionGoalCard from '@/components/chat/SessionGoalCard.vue'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectTrigger,
} from '@/components/ui/select'
import {
  SelectItem as RadixSelectItem,
  SelectItemIndicator as RadixSelectItemIndicator,
  SelectItemText as RadixSelectItemText,
} from 'radix-vue'
import { useChatPage } from '@/composables/chat/useChatPage.js'
import { usePanelStore } from '@/stores/panel.js'
import { useWorkbenchStore } from '@/stores/workbench.js'
import { storeToRefs } from 'pinia'
import { useLanguage } from '@/utils/i18n.js'
import { getMessageLabel } from '@/utils/messageLabels'
import { taskAPI } from '@/api/task.js'
import { chatAPI } from '@/api/chat.js'
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

const { t } = useLanguage()
const displayMode = ref(CHAT_DISPLAY_MODES.EXECUTION)
const expandedGroupIds = ref(new Set())
const DISPLAY_MODE_STORAGE_KEY = 'chatDisplayModePreference'

const panelStore = usePanelStore()
const { showWorkbench, showWorkspace } = storeToRefs(panelStore)
const workbenchStore = useWorkbenchStore()

const {
  agents,
  selectedAgent,
  selectedAgentId,
  config,
  messagesListRef,
  messagesEndRef,
  showLoadingBubble,
  filteredMessages,
  currentGoal,
  currentGoalTransition,
  isGoalMutating,
  isLoading,
  isCurrentSessionLoading,
  handleAgentChange,
  handleWorkspacePanel,
  togglePanel,
  openWorkbench,
  handleScroll,
  handleSendMessage,
  stopGeneration,
  currentSessionId,
  activeSubSessionId,
  subSessionMessages,
  handleCloseSubSession,
  handleOpenSubSession,
  downloadWorkspaceFile,
  workspaceFiles,
  isWorkspaceLoading,
  downloadFile,
  deleteFile,
  updateConfig,
  refreshWorkspace,
  // 能力面板相关
  abilityItems,
  abilityLoading,
  abilityError,
  showAbilityPanel,
  abilityPresetInput,
  showAbilityButton,
  hasUsedAbilityEntryInSession,
  danmakuResetTrigger,
  isViewingHistorySession,
  danmakuClosedByUser,
  openAbilityPanel,
  closeAbilityPanel,
  retryAbilityFetch,
  onAbilityCardClick,
  submitEditedLastUserMessage,
  saveSessionGoal,
  clearSessionGoal,
  completeSessionGoal
  applyGuidanceNow
} = useChatPage(props)

const normalizedMessages = computed(() => normalizeChatMessages(filteredMessages.value))
const editingUserMessageId = ref(null)
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

// 用户点击弹幕关闭键时记录，切换页面再回来不重置弹幕
const onDanmakuClose = () => {
  danmakuClosedByUser.value = true
}

// 能力按钮点击：仅在本会话首次点击时打开能力面板，并隐藏入口按钮
const handleClickAbilityButton = () => {
  if (!showAbilityPanel.value) {
    openAbilityPanel()
  }
  showAbilityButton.value = false
  hasUsedAbilityEntryInSession.value = true
}

// 发送消息后清空能力预置输入
const handleSendMessageWithAbilityClear = async (content, options) => {
  if (isCurrentSessionLoading.value && currentSessionId.value && typeof content === 'string' && content.trim()) {
    abilityPresetInput.value = ''
    const guidanceId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : `g-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const sid = currentSessionId.value
    workbenchStore.addGuidance(sid, { guidanceId, content })
    try {
      await chatAPI.injectUserMessage(sid, content, guidanceId)
    } catch (e) {
      console.warn('[Chat] injectUserMessage failed:', e)
      workbenchStore.removeGuidance(sid, guidanceId)
      toast.error(t('guidance.injectFailed') || '加入引导失败')
    }
    return
  }
  handleSendMessage(content, options)
  abilityPresetInput.value = ''
}

// 确认对话框引用
const confirmDialogRef = ref(null)

// 消息输入框引用
const messageInputRef = ref(null)

// 处理删除文件 - 带确认对话框
const handleDeleteFile = async (item) => {
  const confirmed = await confirmDialogRef.value?.confirm(
    t('common.confirmDelete') || '确定要删除此文件吗？',
    { title: t('common.confirm') || '确认' }
  )
  if (!confirmed) return

  // 调用原始的 deleteFile
  await deleteFile(item)
}

// 处理引用路径 - 将路径添加到主消息输入框
const handleQuotePath = (path) => {
  // 使用 {workspace_root}/ 前缀，让 AI 知道这是工作空间路径
  const pathToInsert = `\`{workspace_root}/${path}\``

  // 添加到主消息输入框
  if (messageInputRef.value) {
    messageInputRef.value.appendInputValue(pathToInsert)
  }
}

// 处理上传文件
const workspacePanelRef = ref(null)

const handleUploadFiles = async (files) => {
  if (!selectedAgentId.value || files.length === 0) return
  
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
      
      // 获取目标路径（文件夹）
      const targetPath = relativePath.includes('/') 
        ? relativePath.substring(0, relativePath.lastIndexOf('/'))
        : ''
      
      await taskAPI.uploadWorkspaceFile(selectedAgentId.value, file, targetPath)
      uploadedCount++
    }
    
    workspacePanelRef.value?.setUploadStatus('上传完成', 100)
    toast.success(`成功上传 ${uploadedCount} 个文件`)
    
    // 刷新工作空间文件列表
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

// 计算是否有面板打开
const anyPanelOpen = computed(() => showWorkspace.value || showWorkbench.value)

// 是否进入“覆盖聊天空态”的能力面板模式：
// 只要：显示能力面板 + 当前会话无消息，即覆盖掉“开始新的对话”空态区域
const overlayAbilityPanel = computed(() => {
  const noMessages = !filteredMessages.value || filteredMessages.value.length === 0
  return showAbilityPanel.value && noMessages
})

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
