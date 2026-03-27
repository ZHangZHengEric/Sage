<template>
  <div class="flex flex-col h-full bg-background">
    <div class="flex-none h-16 flex items-center px-6 justify-end bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/60 z-10 sticky top-0">
      <div class="flex items-center gap-2">
        <Select :model-value="selectedAgentId" @update:model-value="handleAgentChange">
          <SelectTrigger class="w-[160px] h-9 px-2.5 border-muted-foreground/20 bg-muted/50 hover:bg-muted/80 transition-colors focus:ring-1 focus:ring-primary/20 rounded-full">
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
              <SelectItem
                v-for="agent in (agents || [])"
                :key="agent.id"
                :value="agent.id"
                class="relative p-1.5 cursor-pointer rounded-lg hover:bg-muted/80 focus:bg-muted/80 data-[state=checked]:bg-primary/10 transition-colors"
              >
                <div class="flex flex-col items-center gap-1 w-full">
                  <div class="relative w-9 h-9 rounded-lg overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5">
                    <img
                      :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(agent.id)}`"
                      :alt="agent.name"
                      class="w-full h-full object-cover"
                    />
                  </div>
                  <div class="flex items-center justify-center gap-1 w-full">
                    <span
                      v-if="selectedAgentId === agent.id"
                      class="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0"
                    />
                    <span class="text-[10px] font-medium text-foreground text-center truncate leading-none">
                      {{ agent.name }}
                    </span>
                  </div>
                </div>
              </SelectItem>
            </div>
          </SelectContent>
        </Select>

        <div class="h-4 w-[1px] bg-border mx-1"></div>

        <TooltipProvider>
          <div class="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="toggleWorkbench">
                  <Monitor class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workbench.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="toggleWorkspace">
                  <FolderOpen class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workspace.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="handleShare">
                  <Share2 class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('chat.share') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="toggleSettings">
                  <Settings class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('chat.settings') }}</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </TooltipProvider>
      </div>
    </div>

    <div class="flex-1 overflow-hidden flex flex-row pb-6">
      <div
        class="flex-1 flex flex-col min-w-0 bg-muted/5 relative transition-all duration-200"
        :class="{ 'mr-0': !anyPanelOpen }"
      >
        <div ref="messagesListRef" class="flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth" @scroll="handleScroll">
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
            <p class="mb-8 text-sm max-w-md mx-auto leading-relaxed text-muted-foreground/80">{{ t('chat.emptyDesc') }}</p>
          </div>

          <div v-else class="pb-8 max-w-4xl mx-auto w-full">
            <MessageRenderer
              v-for="(message, index) in filteredMessages"
              :key="message.id || message.message_id || index"
              :message="message"
              :messages="filteredMessages"
              :message-index="index"
              :agent-id="selectedAgentId"
              :is-loading="isLoading && index === filteredMessages.length - 1"
              @download-file="downloadWorkspaceFile"
              @sendMessage="handleSendMessage"
              @openSubSession="handleOpenSubSession"
            />

            <div v-if="showLoadingBubble" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
              <LoadingBubble />
            </div>
          </div>
          <div ref="messagesEndRef" />
        </div>

        <div class="flex-none p-4 bg-background" v-if="selectedAgent">
          <div class="w-full max-w-[800px] mx-auto">
            <MessageInput
              :agent-id="selectedAgentId"
              :is-loading="isCurrentSessionLoading"
              :selected-agent="selectedAgent"
              @send-message="handleSendMessage"
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
        @close="handleCloseSubSession"
        @download-file="downloadWorkspaceFile"
        @openSubSession="handleOpenSubSession"
      />

      <Transition name="panel">
        <WorkspacePanel
          v-if="panelStore.showWorkspace"
          :workspace-files="workspaceFiles"
          @download-file="downloadFile"
          @close="panelStore.closeAll()"
        />
      </Transition>

      <Transition name="panel">
        <WorkbenchPreview
          v-if="panelStore.showWorkbench"
          :messages="filteredMessages"
          :session-id="currentSessionId"
          @close="panelStore.closeAll()"
        />
      </Transition>

      <Transition name="panel">
        <ConfigPanel
          v-if="panelStore.showSettings"
          :agents="agents"
          :selected-agent="selectedAgent"
          :config="config"
          @config-change="updateConfig"
          @close="panelStore.closeAll()"
        />
      </Transition>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'Chat' })

import { computed, watch } from 'vue'
import { Bot, Settings, Share2, FolderOpen, Monitor } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ConfigPanel from '@/components/chat/ConfigPanel.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'
import WorkbenchPreview from '@/components/chat/WorkbenchPreview.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import SubSessionPanel from '@/components/chat/SubSessionPanel.vue'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger
} from '@/components/ui/select'
import { useChatPage } from '@/composables/chat/useChatPage.js'
import { useWorkbenchStore } from '@/stores/workbench'
import { usePanelStore } from '@/stores/panel'

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
  isLoading,
  isCurrentSessionLoading,
  currentSessionId,
  messagesListRef,
  messagesEndRef,
  handleAgentChange,
  handleShare,
  handleScroll,
  handleSendMessage,
  stopGeneration,
  activeSubSessionId,
  subSessionMessages,
  handleCloseSubSession,
  handleOpenSubSession,
  downloadWorkspaceFile,
  workspaceFiles,
  downloadFile,
  updateConfig
} = useChatPage(props)

const workbenchStore = useWorkbenchStore()
const panelStore = usePanelStore()

const toggleWorkbench = () => {
  panelStore.toggleWorkbench()
}

const toggleWorkspace = () => {
  panelStore.toggleWorkspace()
}

const toggleSettings = () => {
  panelStore.toggleSettings()
}

const anyPanelOpen = computed(() => (
  panelStore.showWorkspace || panelStore.showSettings || panelStore.showWorkbench
))

watch(() => currentSessionId.value, (id) => {
  if (id) workbenchStore.setSessionId(id)
}, { immediate: true })
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
</style>
