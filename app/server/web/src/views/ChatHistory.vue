<template>
  <div class="h-full flex flex-col bg-background px-4 py-3">
    <div class="flex-1 flex min-h-0 flex-col">
      <div class="mb-3 flex items-center justify-between gap-3 border-b border-border/55 pb-3">
        <div class="flex min-w-0 items-center gap-3">
          <div class="min-w-0">
            <h1 class="text-[15px] font-semibold tracking-tight text-foreground">{{ t('history.title') }}</h1>
            <p class="text-[11px] text-muted-foreground">{{ totalCount }} {{ t('history.totalConversations') }}</p>
          </div>

          <div class="hidden h-5 w-px bg-border/60 lg:block" />

          <div class="hidden items-center gap-2 lg:flex">
            <div class="relative w-[240px]">
              <Input
                v-model="searchTerm"
                :placeholder="t('history.search')"
                class="h-8 rounded-xl border-border/50 bg-background/60 pl-8 text-[12px] shadow-none dark:bg-background/20"
              />
              <Search class="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground/75" />
            </div>

            <Select v-model="filterAgent">
              <SelectTrigger class="h-8 w-[118px] rounded-xl border-border/50 bg-background/60 text-[12px] shadow-none dark:bg-background/20">
                <SelectValue :placeholder="t('history.all')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{{ t('history.all') }}</SelectItem>
                <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                  {{ agent.name }}
                </SelectItem>
              </SelectContent>
            </Select>

            <Select v-model="filterGoalStatus">
              <SelectTrigger class="h-8 w-[118px] rounded-xl border-border/50 bg-background/60 text-[12px] shadow-none dark:bg-background/20">
                <SelectValue :placeholder="t('history.goalStatusAll')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{{ t('history.goalStatusAll') }}</SelectItem>
                <SelectItem value="active">{{ t('chat.goalStatus.active') }}</SelectItem>
                <SelectItem value="paused">{{ t('chat.goalStatus.paused') }}</SelectItem>
                <SelectItem value="completed">{{ t('chat.goalStatus.completed') }}</SelectItem>
                <SelectItem value="none">{{ t('history.goalStatusNone') }}</SelectItem>
              </SelectContent>
            </Select>

            <Select v-model="sortBy">
              <SelectTrigger class="h-8 w-[92px] rounded-xl border-border/50 bg-background/60 text-[12px] shadow-none dark:bg-background/20">
                <SelectValue :placeholder="t('history.sortByDate')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="date">{{ t('history.sortByDate') }}</SelectItem>
                <SelectItem value="title">{{ t('history.sortByTitle') }}</SelectItem>
                <SelectItem value="messages">{{ t('history.sortByMessages') }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div class="hidden items-center rounded-full border border-border/60 bg-background/60 px-2.5 py-1 text-[11px] text-muted-foreground md:flex dark:bg-background/20">
          {{ t('common.page') }} {{ currentPage }} / {{ Math.ceil(totalCount / pageSize) || 1 }}
        </div>
      </div>

      <div class="mb-3 flex items-center gap-2 lg:hidden">
        <div class="relative w-full max-w-md flex-1">
          <Input
            v-model="searchTerm"
            :placeholder="t('history.search')"
            class="h-8.5 rounded-xl border-border/50 bg-background/60 pl-8 text-[12px] shadow-none dark:bg-background/20"
          />
          <Search class="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground/75" />
        </div>

        <div class="flex gap-2 items-center">
          <Select v-model="filterAgent">
            <SelectTrigger class="h-8.5 w-[118px] rounded-xl border-border/50 bg-background/60 text-[12px] shadow-none dark:bg-background/20">
              <SelectValue :placeholder="t('history.all')" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{{ t('history.all') }}</SelectItem>
              <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                {{ agent.name }}
              </SelectItem>
            </SelectContent>
          </Select>

          <Select v-model="filterGoalStatus">
            <SelectTrigger class="h-8.5 w-[118px] rounded-xl border-border/50 bg-background/60 text-[12px] shadow-none dark:bg-background/20">
              <SelectValue :placeholder="t('history.goalStatusAll')" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{{ t('history.goalStatusAll') }}</SelectItem>
              <SelectItem value="active">{{ t('chat.goalStatus.active') }}</SelectItem>
              <SelectItem value="paused">{{ t('chat.goalStatus.paused') }}</SelectItem>
              <SelectItem value="completed">{{ t('chat.goalStatus.completed') }}</SelectItem>
              <SelectItem value="none">{{ t('history.goalStatusNone') }}</SelectItem>
            </SelectContent>
          </Select>

          <Select v-model="sortBy">
            <SelectTrigger class="h-8.5 w-[92px] rounded-xl border-border/50 bg-background/60 text-[12px] shadow-none dark:bg-background/20">
              <SelectValue :placeholder="t('history.sortByDate')" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="date">{{ t('history.sortByDate') }}</SelectItem>
              <SelectItem value="title">{{ t('history.sortByTitle') }}</SelectItem>
              <SelectItem value="messages">{{ t('history.sortByMessages') }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto pr-1">
        <div v-if="isLoading" class="flex flex-col gap-4 p-4 items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>

        <div v-else-if="paginatedConversations.length > 0" class="overflow-hidden rounded-[18px] border border-border/50 bg-background/30 dark:bg-background/10">
          <div
            v-for="(conversation, index) in paginatedConversations"
            :key="conversation.id"
            :class="[
              'group relative grid cursor-pointer grid-cols-[auto,minmax(0,1fr),auto] items-center gap-3 px-3 py-2 transition-all duration-200 hover:bg-foreground/[0.025] dark:hover:bg-white/[0.025]',
              { 'bg-primary/[0.045]': selectedConversations.has(conversation.id) },
              { 'border-t border-border/60': index > 0 }
            ]"
            @click="handleSelectConversation(conversation)"
          >
            <div class="flex-shrink-0">
              <img
                :src="getAgentAvatar(conversation.agent_id)"
                :alt="getAgentName(conversation.agent_id)"
                class="h-8 w-8 rounded-lg object-cover bg-muted ring-1 ring-border/30"
                @error="$event.target.src = 'https://api.dicebear.com/9.x/bottts/svg?seed=default'"
              />
            </div>

            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <h3 class="min-w-0 flex-1 truncate text-[14px] font-semibold tracking-tight text-foreground">
                  {{ conversation.display_title || conversation.title }}
                </h3>
                <Badge
                  v-if="conversation.goal?.status"
                  variant="outline"
                  class="hidden h-5 shrink-0 rounded-full px-2 text-[10px] lg:inline-flex"
                >
                  {{ t(`chat.goalStatus.${conversation.goal.status}`) || conversation.goal.status }}
                </Badge>
                <div class="hidden shrink-0 items-center gap-2 overflow-hidden text-[11px] text-muted-foreground lg:flex">
                  <div class="flex min-w-0 items-center gap-1.5 rounded-full bg-muted/18 px-1.5 py-0.5 ring-1 ring-border/20">
                    <Bot class="h-3 w-3 text-primary/80" />
                    <span class="truncate font-medium text-foreground/85">{{ getAgentName(conversation.agent_id) }}</span>
                  </div>

                  <span class="text-border/80">·</span>

                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <button
                          class="inline-flex shrink-0 items-center gap-1 rounded-full px-1 py-0.5 text-muted-foreground transition-colors hover:bg-muted/18 hover:text-primary"
                          @click.stop
                        >
                          <Info class="h-3 w-3" />
                          <span>{{ t('common.id') }}</span>
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="top" class="max-w-xs p-3">
                        <div class="space-y-2">
                          <p class="font-medium text-sm">{{ t('common.sessionId') }}</p>
                          <p class="font-mono text-xs break-all bg-muted/50 p-2 rounded">{{ conversation.session_id }}</p>
                          <Button
                            size="sm"
                            variant="secondary"
                            class="w-full text-xs"
                            @click.stop="copySessionId(conversation)"
                          >
                            <Copy class="w-3 h-3 mr-1" />
                            {{ t('history.copySessionId') }}
                          </Button>
                        </div>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>

                  <template v-if="conversation.trace_url">
                    <span class="text-border/80">·</span>
                    <button
                      class="inline-flex shrink-0 items-center gap-1 rounded-full px-1 py-0.5 text-muted-foreground transition-colors hover:bg-muted/18 hover:text-primary"
                      @click.stop="handleOpenTrace(conversation)"
                    >
                      <Activity class="h-3 w-3" />
                      <span>{{ t('history.trace') }}</span>
                    </button>
                  </template>

                  <span class="text-border/80">·</span>

                  <span class="truncate text-muted-foreground/80">{{ formatDateTime(conversation.updated_at) }}</span>
                </div>
              </div>

              <div
                v-if="conversation.goal?.objective"
                class="mt-1 truncate text-[11px] text-muted-foreground/85"
              >
                {{ t('chat.currentGoal') }} · {{ conversation.goal.objective }}
              </div>

              <div class="mt-0.5 flex items-center gap-2 overflow-hidden text-[11px] text-muted-foreground lg:hidden">
                <Badge
                  v-if="conversation.goal?.status"
                  variant="outline"
                  class="h-5 shrink-0 rounded-full px-2 text-[10px]"
                >
                  {{ t(`chat.goalStatus.${conversation.goal.status}`) || conversation.goal.status }}
                </Badge>
                <div class="flex min-w-0 items-center gap-1.5 rounded-full bg-muted/18 px-1.5 py-0.5 ring-1 ring-border/20">
                  <Bot class="h-3 w-3 text-primary/80" />
                  <span class="truncate font-medium text-foreground/85">{{ getAgentName(conversation.agent_id) }}</span>
                </div>

                <span class="text-border/80">·</span>

                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button
                        class="inline-flex shrink-0 items-center gap-1 rounded-full px-1 py-0.5 text-muted-foreground transition-colors hover:bg-muted/18 hover:text-primary"
                        @click.stop
                      >
                        <Info class="h-3 w-3" />
                        <span>{{ t('common.id') }}</span>
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" class="max-w-xs p-3">
                      <div class="space-y-2">
                        <p class="font-medium text-sm">{{ t('common.sessionId') }}</p>
                        <p class="font-mono text-xs break-all bg-muted/50 p-2 rounded">{{ conversation.session_id }}</p>
                        <Button
                          size="sm"
                          variant="secondary"
                          class="w-full text-xs"
                          @click.stop="copySessionId(conversation)"
                        >
                          <Copy class="w-3 h-3 mr-1" />
                          {{ t('history.copySessionId') }}
                        </Button>
                      </div>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>

                <span class="truncate text-muted-foreground/80">{{ formatDateTime(conversation.updated_at) }}</span>
              </div>
            </div>

            <div class="flex items-center gap-0.5 self-stretch">
              <div class="flex items-center gap-1 rounded-full bg-muted/18 px-2 py-0.5 text-[10px] text-muted-foreground ring-1 ring-border/20">
                <Clock class="h-3 w-3" />
                <span>{{ formatRelativeTime(conversation.updated_at) }}</span>
              </div>

              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-7.5 w-7.5 rounded-full text-muted-foreground/75 opacity-0 transition-all hover:bg-primary/10 hover:text-primary group-hover:opacity-100"
                      @click.stop="handleShareConversation(conversation)"
                    >
                      <Download class="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    <p>{{ t('history.export') }}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-7.5 w-7.5 rounded-full text-muted-foreground/75 opacity-0 transition-all hover:bg-primary/10 hover:text-primary group-hover:opacity-100"
                      @click.stop="handleCopyShareLink(conversation)"
                    >
                      <Share2 class="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    <p>{{ t('history.shareLink') }}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <TooltipProvider v-if="conversation.trace_url">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-7.5 w-7.5 rounded-full text-muted-foreground/75 opacity-0 transition-all hover:bg-primary/10 hover:text-primary group-hover:opacity-100"
                      @click.stop="handleOpenTrace(conversation)"
                    >
                      <Activity class="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    <p>{{ t('history.trace') }}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <TooltipProvider v-if="canDelete(conversation)">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-7.5 w-7.5 rounded-full text-muted-foreground/75 opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                      @click.stop="handleDeleteConversation(conversation)"
                    >
                      <Trash2 class="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    <p>{{ t('common.delete') }}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </div>
        </div>

        <div v-if="!isLoading && totalCount === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground min-h-[300px]">
          <div class="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mb-4">
            <MessageCircle class="w-10 h-10 opacity-50" />
          </div>
          <h3 class="text-lg font-medium mb-2">{{ t('history.noConversations') }}</h3>
          <p class="text-sm">{{ t('history.noConversationsDesc') }}</p>
        </div>
      </div>

      <div v-if="totalCount > 0" class="mt-2 flex items-center justify-center gap-4 border-t border-border/55 py-3">
        <Button
          variant="outline"
          size="sm"
          class="h-8 rounded-full border-border/50 bg-background/40 px-4 text-[12px] shadow-none dark:bg-background/15"
          :disabled="currentPage <= 1"
          @click="handlePageChange(currentPage - 1)"
        >
          {{ t('common.previous') }}
        </Button>
        <span class="text-sm text-muted-foreground">
          {{ t('common.page') }} {{ currentPage }} / {{ Math.ceil(totalCount / pageSize) }}
        </span>
        <Button
          variant="outline"
          size="sm"
          class="h-8 rounded-full border-border/50 bg-background/40 px-4 text-[12px] shadow-none dark:bg-background/15"
          :disabled="currentPage * pageSize >= totalCount"
          @click="handlePageChange(currentPage + 1)"
        >
          {{ t('common.next') }}
        </Button>
      </div>
    </div>

    <Dialog :open="showShareModal" @update:open="showShareModal = $event">
      <DialogContent class="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{{ t('history.shareTitle') }}</DialogTitle>
          <DialogDescription>{{ t('history.exportFormat') }}</DialogDescription>
        </DialogHeader>
        <div class="py-4">
          <div class="grid gap-3 sm:grid-cols-3">
            <Button class="w-full" @click="handleExportToMarkdown">
              <FileText class="w-4 h-4 mr-2" />
              {{ t('history.exportMarkdown') }}
            </Button>
            <Button class="w-full" variant="outline" @click="handleExportToHTML">
              <FileCode class="w-4 h-4 mr-2" />
              {{ t('history.exportHTML') }}
            </Button>
            <Button class="w-full" variant="secondary" @click="handleCopyShareLinkFromDialog">
              <Share2 class="w-4 h-4 mr-2" />
              {{ t('history.shareLink') }}
            </Button>
          </div>
          <div class="mt-4 p-4 bg-muted/50 rounded-lg text-sm space-y-2">
            <p><strong>{{ t('history.conversationTitle') }}</strong>: {{ shareConversation?.display_title || shareConversation?.title }}</p>
            <p><strong>{{ t('history.messageCount') }}</strong>: {{ getVisibleMessageCount() }} {{ t('history.visibleMessages') }}</p>
            <p class="font-mono text-[11px] break-all text-muted-foreground/85">{{ shareConversation ? buildShareUrl(shareConversation.session_id) : '' }}</p>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- 确认对话框 -->
    <AppConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { MessageCircle, Search, Clock, Bot, Loader, Trash2, Download, Activity, Info, Copy, FileText, FileCode, Share2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useLanguage } from '@/utils/i18n.js'
import { exportToHTML, exportToMarkdown } from '@/utils/exporter.js'
import { agentAPI } from '@/api/agent.js'
import { chatAPI } from '@/api/chat.js'
import { getCurrentUser } from '@/utils/auth.js'
import { sanitizeSessionTitle } from '@/utils/sessionTitle'
import { isTokenUsageMessage } from '@/utils/messageLabels.js'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

defineEmits(['select-conversation'])

const router = useRouter()
const route = useRoute()
const agents = ref([])
const { t } = useLanguage()
const searchTerm = ref(route.query.search || '')
const filterAgent = ref(route.query.agent_id || 'all')
const filterGoalStatus = ref(route.query.goal_status || 'all')
const sortBy = ref(route.query.sort_by || 'date')
const selectedConversations = ref(new Set())
const showShareModal = ref(false)
const shareConversation = ref(null)
const currentUser = ref(null)

// 确认对话框引用
const confirmDialogRef = ref(null)

const currentPage = ref(parseInt(route.query.page) || 1)
const pageSize = ref(18)
const totalCount = ref(0)
const paginatedConversations = ref([])
const isLoading = ref(true)

const loadAgents = async () => {
  try {
    const agentList = await agentAPI.getAgents()
    agents.value = agentList || []
  } catch {
    agents.value = []
  }
}

const getAgentAvatar = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  if (agent) {
    return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agent.id)}`
  }
  return 'https://api.dicebear.com/9.x/bottts/svg?seed=default'
}

const loadConversationsPaginated = async () => {
  try {
    isLoading.value = true
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchTerm.value || undefined,
      agent_id: filterAgent.value !== 'all' ? filterAgent.value : undefined,
      goal_status: filterGoalStatus.value !== 'all' ? filterGoalStatus.value : undefined,
      sort_by: sortBy.value,
    }
    const response = await chatAPI.getConversationsPaginated(params)
    paginatedConversations.value = (response.list || []).map((conversation) => {
      const displayTitle = sanitizeSessionTitle(conversation?.title || '')
      return {
        ...conversation,
        display_title: displayTitle || t('chat.untitledConversation')
      }
    })
    totalCount.value = response.total || 0
  } catch {
    toast.error(t('history.loadListFailed'))
    paginatedConversations.value = []
    totalCount.value = 0
  } finally {
    isLoading.value = false
  }
}

const handlePageChange = (page) => {
  currentPage.value = page
}

const canDelete = (conversation) => {
  if (!currentUser.value) return false
  if (currentUser.value.role === 'admin') return true
  return currentUser.value.id === conversation.user_id || currentUser.value.userid === conversation.user_id
}

const handleDeleteConversation = async (conversation) => {
  const confirmed = await confirmDialogRef.value?.confirm(
    t('history.deleteConfirm'),
    { title: t('history.deleteConversationTitle') }
  )
  if (!confirmed) return

  try {
    await chatAPI.deleteConversation(conversation.session_id)
    toast.success(t('history.deleteSuccess'))
    loadConversationsPaginated()
  } catch (error) {
    console.error('Failed to delete conversation:', error)
    toast.error(t('history.deleteError'))
  }
}

const handleSelectConversation = (conversation) => {
  router.push({
    path: '/agent/chat',
    query: {
      session_id: conversation.session_id
    }
  })
}

const formatRelativeTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return t('history.justNow')
  if (diffMins < 60) return t('history.minutesAgo', { minutes: diffMins })
  if (diffHours < 24) return t('history.hoursAgo', { hours: diffHours })
  if (diffDays < 7) return t('history.daysAgo', { days: diffDays })

  return formatDateTime(timestamp)
}

const formatDateTime = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

const getAgentName = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  return agent ? agent.name : t('chat.unknownAgent')
}

const buildShareUrl = (sessionId) => {
  if (!sessionId) return ''
  const rawBase = (import.meta.env?.BASE_URL || '/').toString()
  const base = rawBase.endsWith('/') ? rawBase : `${rawBase}/`
  return `${window.location.origin}${base}share/${sessionId}`
}

const copyTextToClipboard = async (text) => {
  if (!text) return false
  try {
    if (navigator?.clipboard?.writeText && window.isSecureContext !== false) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch (err) {
    console.warn('navigator.clipboard.writeText failed, falling back:', err)
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch (err) {
    console.error('execCommand copy failed:', err)
    return false
  }
}

const handleCopyShareLink = async (conversation) => {
  const sessionId = conversation?.session_id
  if (!sessionId) {
    toast.error(t('history.shareLinkFailed'))
    return
  }
  const ok = await copyTextToClipboard(buildShareUrl(sessionId))
  if (ok) {
    toast.success(t('history.shareLinkSuccess'))
  } else {
    toast.error(t('history.shareLinkFailed'))
  }
}

const handleCopyShareLinkFromDialog = async () => {
  if (!shareConversation.value) return
  await handleCopyShareLink(shareConversation.value)
}

const handleShareConversation = async (conversation) => {
  shareConversation.value = conversation
  showShareModal.value = true
  try {
    const response = await chatAPI.getConversationMessages(conversation.session_id)
    conversation.messages = response.messages || []
  } catch (err) {
    console.error('Failed to load conversation messages for share dialog:', err)
    conversation.messages = conversation.messages || []
  }
}

const copySessionId = async (conversation) => {
  const text = conversation?.session_id || ''
  if (!text) return
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      toast.success(t('history.sessionIdCopied'))
      return
    }
  } catch (_) {}
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    toast.success(t('history.sessionIdCopied'))
  } catch {
    toast.error(t('history.copyFailed'))
  }
}

const handleOpenTrace = (conversation) => {
  const traceUrl = conversation?.trace_url
  if (!traceUrl) return
  window.open(traceUrl, '_blank', 'noopener,noreferrer')
}

const formatMessageForExport = (messages) => {
  if (!messages || !Array.isArray(messages)) return []

  return messages.map(message => {
    if (message.role === 'user') {
      return { role: 'user', content: message.content }
    } else if (message.role === 'assistant') {
      if (message.tool_calls && message.tool_calls.length > 0) {
        return { role: 'assistant', tool_calls: message.tool_calls }
      } else if (message.content && message.content !== '' && message.content !== false) {
        return { role: 'assistant', content: message.content }
      }
    } else if (message.role === 'tool') {
      return {
        role: 'tool',
        content: message.content,
        tool_call_id: message.tool_call_id
      }
    }
    return null
  }).filter(Boolean)
}

const getVisibleMessageCount = () => {
  if (!shareConversation.value?.messages) return 0
  return shareConversation.value.messages.filter(msg =>
    msg.role === 'user' || (msg.role === 'assistant' && !isTokenUsageMessage(msg) && msg.content && msg.content !== '' && msg.content !== false)
  ).length
}

const handleExportToMarkdown = () => {
  if (!shareConversation.value) return
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  exportToMarkdown(shareConversation.value, getAgentName(shareConversation.value.agent_id), visibleMessages)
  showShareModal.value = false
  toast.success(t('history.markdownExported'))
}

const handleExportToHTML = () => {
  if (!shareConversation.value) return
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  exportToHTML(shareConversation.value, visibleMessages)
  showShareModal.value = false
  toast.success(t('history.htmlExported'))
}

const updateUrlParams = () => {
  router.replace({
    query: {
      ...route.query,
      search: searchTerm.value || undefined,
      agent_id: filterAgent.value !== 'all' ? filterAgent.value : undefined,
      goal_status: filterGoalStatus.value !== 'all' ? filterGoalStatus.value : undefined,
      sort_by: sortBy.value,
      page: currentPage.value > 1 ? String(currentPage.value) : undefined
    }
  })
}

watch([searchTerm, filterAgent, filterGoalStatus, sortBy], () => {
  if (currentPage.value !== 1) {
    currentPage.value = 1
  } else {
    updateUrlParams()
    loadConversationsPaginated()
  }
}, { deep: true })

watch(currentPage, () => {
  updateUrlParams()
  loadConversationsPaginated()
})

onMounted(async () => {
  currentUser.value = getCurrentUser()
  await loadAgents()
  await loadConversationsPaginated()
})
</script>

<style scoped>
</style>
