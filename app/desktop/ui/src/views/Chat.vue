<template>
  <div class="flex flex-col h-full bg-background">
    <div class="flex-none h-16 flex items-center px-6 justify-end bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/60 z-10 sticky top-0">

      <div class="flex items-center gap-2 ">
        <!-- Agent 选择器 - 紧凑网格布局 -->
        <Select :model-value="selectedAgentId" @update:model-value="handleAgentChange">
          <SelectTrigger class="w-[160px] h-9 px-2.5 border-muted-foreground/20 bg-muted/50 hover:bg-muted/80 transition-colors focus:ring-1 focus:ring-primary/20 rounded-full">
            <div class="flex items-center gap-2 w-full">
              <!-- Agent 头像 -->
              <div class="w-5 h-5 rounded-full overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/10">
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
              <SelectItem
                v-for="agent in (agents || [])"
                :key="agent.id"
                :value="agent.id"
                class="relative p-1.5 cursor-pointer rounded-lg hover:bg-muted/80 focus:bg-muted/80 data-[state=checked]:bg-primary/10 transition-colors"
              >
                <div class="flex flex-col items-center gap-1 w-full">
                  <!-- Agent 头像 -->
                  <div class="relative w-9 h-9 rounded-lg overflow-hidden flex-shrink-0 bg-gradient-to-br from-primary/20 to-primary/5">
                    <img
                      :src="`https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,square01,square02&seed=${encodeURIComponent(agent.id)}`"
                      :alt="agent.name"
                      class="w-full h-full object-cover"
                    />
                  </div>
                  <!-- Agent 名称 -->
                  <div class="flex items-center justify-center gap-1 w-full">
                    <!-- 选中状态指示器 - 绿色圆点 -->
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
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="togglePanel('workbench')">
                  <Monitor class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workbench.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="togglePanel('workspace')">
                  <FolderOpen class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('workspace.title') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="togglePanel('settings')">
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
      <!-- 主聊天区域 -->
      <div
        class="flex-1 flex flex-col min-w-0 bg-muted/5 relative transition-all duration-200"
        :class="{ 'mr-0': !anyPanelOpen }"
      >
        <!-- 弹幕叠在聊天区域上方；能力面板打开或用户已发送消息时不渲染弹幕 -->
        <div v-if="!showAbilityPanel && filteredMessages.length === 0" class="absolute top-5 left-0 right-0 h-[25%] min-h-[100px] max-h-[180px] overflow-hidden pointer-events-none z-10">
          <AgentUsageDanmaku :hide-for-history="isViewingHistorySession" :closed-by-user="danmakuClosedByUser" :reset-trigger="danmakuResetTrigger" @close="onDanmakuClose" />
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
              <MessageRenderer
                v-for="(message, index) in filteredMessages"
                :key="message.id || index"
                :message="message"
                :messages="filteredMessages"
                :message-index="index"
                :agent-id="selectedAgentId"
                :is-loading="isLoading && index === filteredMessages.length - 1"
                :open-workbench="openWorkbench"
                @download-file="downloadWorkspaceFile"
                @sendMessage="handleSendMessage"
                @openSubSession="handleOpenSubSession"
              />

              <!-- Global loading indicator when等待首个响应块 -->
              <div v-if="showLoadingBubble" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
                <LoadingBubble />
              </div>
            </div>
          </template>
          <div ref="messagesEndRef" />
        </div>

        <div class="flex-none p-4 bg-background" v-if="selectedAgent">
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
              :is-loading="isCurrentSessionLoading"
              :preset-text="abilityPresetInput"
              :selected-agent="selectedAgent"
              @send-message="handleSendMessageWithAbilityClear"
              @stop-generation="stopGeneration"
            />
          </div>
        </div>
      </div>

      <!-- 右侧面板区域 -->
      <TransitionGroup name="panel">
        <WorkspacePanel
          v-if="showWorkspace"
          ref="workspacePanelRef"
          :workspace-files="workspaceFiles"
          :agent-id="selectedAgentId"
          @download-file="downloadFile"
          @delete-file="deleteFile"
          @quote-path="handleQuotePath"
          @upload-files="handleUploadFiles"
          @close="showWorkspace = false"
        />

        <ConfigPanel
          v-else-if="showSettings"
          :agents="agents"
          :selected-agent="selectedAgent"
          :config="config"
          @config-change="updateConfig"
          @close="showSettings = false"
        />

        <WorkbenchPreview
          v-else-if="showWorkbench && currentSessionId"
          :messages="filteredMessages"
          :session-id="currentSessionId"
          @close="showWorkbench = false"
        />
      </TransitionGroup>

      <SubSessionPanel
        :is-open="!!activeSubSessionId"
        :session-id="activeSubSessionId"
        :messages="subSessionMessages"
        :is-loading="isLoading"
        @close="handleCloseSubSession"
        @download-file="downloadWorkspaceFile"
        @openSubSession="handleOpenSubSession"
      />
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'Chat' })
import { computed, ref } from 'vue'
import { Bot, Settings, FolderOpen, Monitor, Sparkles } from 'lucide-vue-next'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ConfigPanel from '@/components/chat/ConfigPanel.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'
import SubSessionPanel from '@/components/chat/SubSessionPanel.vue'
import WorkbenchPreview from '@/components/chat/WorkbenchPreview.vue'
import AbilityPanel from '@/components/chat/AbilityPanel.vue'
import AgentUsageDanmaku from '@/components/chat/AgentUsageDanmaku.vue'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useChatPage } from '@/composables/chat/useChatPage.js'
import { usePanelStore } from '@/stores/panel.js'
import { storeToRefs } from 'pinia'
import { useLanguage } from '@/utils/i18n.js'
import { taskAPI } from '@/api/task.js'
import { toast } from 'vue-sonner'

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

const panelStore = usePanelStore()
const { showWorkbench, showWorkspace, showSettings } = storeToRefs(panelStore)

const {
  agents,
  selectedAgent,
  selectedAgentId,
  config,
  messagesListRef,
  messagesEndRef,
  showLoadingBubble,
  filteredMessages,
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
  onAbilityCardClick
} = useChatPage(props)

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
const handleSendMessageWithAbilityClear = (content, options) => {
  handleSendMessage(content, options)
  abilityPresetInput.value = ''
}

// 处理引用路径 - 将路径添加到输入框
const handleQuotePath = (path) => {
  const currentValue = abilityPresetInput.value || ''
  // 使用 {workspace_root}/ 前缀，让 AI 知道这是工作空间路径
  const pathToInsert = `\`{workspace_root}/${path}\``

  if (currentValue) {
    // 如果输入框已有内容，在末尾添加（前面加空格）
    abilityPresetInput.value = currentValue + ' ' + pathToInsert
  } else {
    // 如果输入框为空，直接添加
    abilityPresetInput.value = pathToInsert
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
const anyPanelOpen = computed(() => showWorkspace.value || showSettings.value || showWorkbench.value)

// 是否进入“覆盖聊天空态”的能力面板模式：
// 只要：显示能力面板 + 当前会话无消息，即覆盖掉“开始新的对话”空态区域
const overlayAbilityPanel = computed(() => {
  const noMessages = !filteredMessages.value || filteredMessages.value.length === 0
  return showAbilityPanel.value && noMessages
})
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
