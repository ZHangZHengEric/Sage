<template>
  <div class="flex flex-col h-full bg-background">
    <div class="flex-none h-16 flex items-center px-6 justify-end bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/60 z-10 sticky top-0">

      <div class="flex items-center gap-2 ">
        <Select :model-value="selectedAgentId" @update:model-value="handleAgentChange">
          <SelectTrigger class="w-[180px] h-9 text-xs border-muted-foreground/20 bg-muted/50 focus:ring-1 focus:ring-primary/20">
            <SelectValue :placeholder="t('chat.selectAgent') || 'Select Agent'" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="agent in (agents || [])" :key="agent.id" :value="agent.id" class="text-xs">
              {{ agent.name }}
            </SelectItem>
          </SelectContent>
        </Select>
        
        <div class="h-4 w-[1px] bg-border mx-1"></div>

        <TooltipProvider>
          <div class="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="handleWorkspacePanel">
                  <FolderOpen class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workspace.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="showSettings = !showSettings">
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
    <div class="flex-1 overflow-hidden relative flex flex-row">
      <div class="flex-1 flex flex-col min-w-0 bg-muted/5 relative">
        <div ref="messagesListRef" class="flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth" @scroll="handleScroll">
          <div v-if="!filteredMessages || filteredMessages.length === 0" class="flex flex-col items-center justify-center text-center p-8 h-full text-muted-foreground animate-in fade-in zoom-in duration-500">
            <div class="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-6 shadow-sm">
               <Bot :size="32" class="opacity-80 text-primary" />
            </div>
            <h3 class="mb-3 text-xl font-semibold text-foreground">{{ t('chat.emptyTitle') }}</h3>
            <p class="mb-8 text-sm max-w-md mx-auto leading-relaxed text-muted-foreground/80">{{ t('chat.emptyDesc') }}</p>
          </div>
          <div v-else class="pb-8 max-w-4xl mx-auto w-full">
            <MessageRenderer 
              v-for="(message, index) in filteredMessages" 
              :key="message.id || index" 
              :message="message"
              :messages="filteredMessages" 
              :message-index="index" 
              :is-loading="isLoading && index === filteredMessages.length - 1"
              @download-file="downloadWorkspaceFile"
              @toolClick="handleToolClick" 
              @sendMessage="handleSendMessage" 
              @openSubSession="handleOpenSubSession"
            />
            
            <!-- Global loading indicator when no messages or waiting for first chunk of response -->
            <div v-if="showLoadingBubble" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
               <LoadingBubble />
            </div>
          </div>
          <div ref="messagesEndRef" />
        </div>
        
        <div class="flex-none p-4  bg-background" v-if="selectedAgent">
            <MessageInput :is-loading="isCurrentSessionLoading" @send-message="handleSendMessage" @stop-generation="stopGeneration" />
        </div>
      </div>

      <SubSessionPanel 
        :is-open="!!activeSubSessionId"
        :session-id="activeSubSessionId"
        :messages="subSessionMessages"
        :is-loading="isLoading"
        @close="handleCloseSubSession"
        @download-file="downloadWorkspaceFile"
        @toolClick="handleToolClick"
        @openSubSession="handleOpenSubSession"
      />

      <WorkspacePanel v-if="showWorkspace" :workspace-files="workspaceFiles"
        @download-file="downloadFile" @close="showWorkspace = false" />

      <ConfigPanel v-if="showSettings" :agents="agents" :selected-agent="selectedAgent" :config="config"
        @config-change="updateConfig" @close="showSettings = false" />
    </div>
  </div>
</template>

<script setup>
import { Bot, Settings, FolderOpen } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ConfigPanel from '@/components/chat/ConfigPanel.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import SubSessionPanel from '@/components/chat/SubSessionPanel.vue'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useChatPage } from '@/composables/chat/useChatPage.js'

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
  messagesListRef,
  messagesEndRef,
  showSettings,
  showWorkspace,
  showLoadingBubble,
  filteredMessages,
  isLoading,
  isCurrentSessionLoading,
  handleAgentChange,
  handleWorkspacePanel,
  handleScroll,
  handleSendMessage,
  stopGeneration,
  activeSubSessionId,
  subSessionMessages,
  handleCloseSubSession,
  handleOpenSubSession,
  downloadWorkspaceFile,
  handleToolClick,
  workspaceFiles,
  downloadFile,
  updateConfig
} = useChatPage(props)
</script>
