<template>
  <div class="h-full flex flex-col p-6 bg-background">
    <div class="bg-background rounded-lg flex-1 flex flex-col min-h-0">
      <!-- 搜索和筛选区域 -->
      <div class="flex gap-4 items-center mb-6">
        <div class="relative w-full max-w-sm flex-1">
          <Input 
            v-model="searchTerm" 
            :placeholder="t('history.search')" 
            class="pl-9"
          />
          <Search class="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        </div>
        
        <div class="flex gap-3 items-center">
          <Select v-model="filterAgent">
            <SelectTrigger class="w-[180px]">
              <SelectValue :placeholder="t('history.all')" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{{ t('history.all') }}</SelectItem>
              <SelectItem v-for="agent in agents" :key="agent.id" :value="agent.id">
                {{ agent.name }}
              </SelectItem>
            </SelectContent>
          </Select>
          
          <Select v-model="sortBy">
            <SelectTrigger class="w-[100px]">
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
      
      <!-- 会话列表 -->
      <div class="flex-1 overflow-y-auto pr-2 space-y-3">
        <!-- 加载状态 -->
        <div v-if="isLoading" class="flex flex-col gap-4 p-4 items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>
        
        <!-- 会话卡片 -->
        <div
          v-else-if="paginatedConversations.length > 0"
          v-for="conversation in paginatedConversations"
          :key="conversation.id"
          :class="[
            'group relative border rounded-xl p-4 transition-all duration-200 hover:shadow-lg hover:border-primary/30 bg-card',
            { 'border-primary ring-1 ring-primary/20': selectedConversations.has(conversation.id) }
          ]"
        >
          <div class="flex items-start gap-4">
            <!-- Agent 头像 -->
            <div class="flex-shrink-0">
              <img
                :src="getAgentAvatar(conversation.agent_id)"
                :alt="getAgentName(conversation.agent_id)"
                class="w-12 h-12 rounded-xl object-cover bg-muted ring-2 ring-border/50"
                @error="$event.target.src = 'https://api.dicebear.com/9.x/bottts/svg?seed=default'"
              />
            </div>
            
            <!-- 主要内容区域 -->
            <div class="flex-1 min-w-0 cursor-pointer" @click="handleSelectConversation(conversation)">
              <!-- 标题行 -->
              <div class="flex items-start justify-between gap-3 mb-2">
                <h3 class="text-base font-semibold text-foreground leading-tight line-clamp-2 flex-1">
                  {{ conversation.display_title || conversation.title }}
                </h3>
                
                <!-- 时间 -->
                <div class="flex items-center gap-1.5 text-xs text-muted-foreground shrink-0 bg-muted/50 px-2 py-1 rounded-full">
                  <Clock class="w-3 h-3" />
                  <span>{{ formatRelativeTime(conversation.updated_at) }}</span>
                </div>
              </div>
              
              <!-- 元信息行 -->
              <div class="flex items-center gap-3 flex-wrap">
                <!-- Agent 名称 -->
                <div class="flex items-center gap-1.5 text-sm">
                  <Bot class="w-3.5 h-3.5 text-primary" />
                  <span class="font-medium text-foreground">{{ getAgentName(conversation.agent_id) }}</span>
                </div>
                
                <!-- 分隔符 -->
                <span class="text-muted-foreground/50">·</span>
                
                <!-- Session ID - 信息图标悬停显示 -->
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button
                        class="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors bg-muted/30 hover:bg-muted/50 px-2 py-0.5 rounded-full cursor-pointer"
                      >
                        <Info class="w-3 h-3" />
                        <span>ID</span>
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" class="max-w-xs p-3">
                      <div class="space-y-2">
                        <p class="font-medium text-sm">Session ID</p>
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
                
                <!-- 完整时间 -->
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <span class="text-xs text-muted-foreground/70 hover:text-muted-foreground transition-colors">
                        {{ formatDateTime(conversation.updated_at) }}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p>{{ t('history.lastUpdated') }}: {{ formatDateTime(conversation.updated_at) }}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            
            <!-- 操作按钮 -->
            <div class="flex flex-col gap-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-primary/10"
                      @click.stop="handleShareConversation(conversation)"
                    >
                      <Download class="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">
                    <p>{{ t('history.share') }}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              
              <TooltipProvider v-if="canDelete(conversation)">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                      @click.stop="handleDeleteConversation(conversation)"
                    >
                      <Trash2 class="h-4 w-4" />
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
        
        <!-- 空状态 -->
        <div v-if="!isLoading && totalCount === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground min-h-[300px]">
          <div class="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mb-4">
            <MessageCircle class="w-10 h-10 opacity-50" />
          </div>
          <h3 class="text-lg font-medium mb-2">{{ t('history.noConversations') }}</h3>
          <p class="text-sm">{{ t('history.noConversationsDesc') }}</p>
        </div>
      </div>
          
      <!-- 分页组件 -->
      <div v-if="totalCount > 0" class="flex items-center justify-center gap-4 py-6 border-t mt-2">
        <Button 
          variant="outline" 
          size="sm" 
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
          :disabled="currentPage * pageSize >= totalCount" 
          @click="handlePageChange(currentPage + 1)"
        >
          {{ t('common.next') }}
        </Button>
      </div>
    </div>
    
    <!-- 导出模态框 -->
    <Dialog :open="showShareModal" @update:open="showShareModal = $event">
      <DialogContent class="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{{ t('history.shareTitle') }}</DialogTitle>
          <DialogDescription>{{ t('history.exportFormat') }}</DialogDescription>
        </DialogHeader>
        <div class="py-4">
          <div class="flex gap-4">
            <Button
              class="flex-1"
              @click="handleExportToMarkdown"
            >
              <FileText class="w-4 h-4 mr-2" />
              {{ t('history.exportMarkdown') }}
            </Button>
            <Button
              class="flex-1"
              variant="outline"
              @click="handleExportToHTML"
            >
              <FileCode class="w-4 h-4 mr-2" />
              {{ t('history.exportHTML') }}
            </Button>
          </div>
          <div class="mt-4 p-4 bg-muted/50 rounded-lg text-sm space-y-2">
            <p><strong>{{ t('history.conversationTitle') }}</strong>: {{ shareConversation?.display_title || shareConversation?.title }}</p>
            <p><strong>{{ t('history.messageCount') }}</strong>: {{ getVisibleMessageCount() }} {{ t('history.visibleMessages') }}</p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { 
  MessageCircle, 
  Search, 
  Clock, 
  Bot, 
  Loader, 
  Trash2, 
  Download,
  Info,
  Copy,
  FileText,
  FileCode
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useLanguage } from '@/utils/i18n.js'
import { exportToHTML, exportToMarkdown } from '@/utils/exporter.js'
import { agentAPI } from '@/api/agent.js'
import { chatAPI } from '@/api/chat.js'
import { getCurrentUser } from '@/utils/auth.js'
import { sanitizeSessionTitle } from '@/utils/sessionTitle'
import { isTokenUsageMessage } from '@/utils/messageLabels.js'

// UI Components
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

// Define emits
const emit = defineEmits(['select-conversation'])

const router = useRouter()
const route = useRoute()

// Get data from stores with null checks
const agents = ref([])
// Composables
const { t, language } = useLanguage()

// State
const searchTerm = ref(route.query.search || '')
const filterAgent = ref(route.query.agent_id || 'all')
const sortBy = ref(route.query.sort_by || 'date')
const selectedConversations = ref(new Set())
const showShareModal = ref(false)
const shareConversation = ref(null)
const currentUser = ref(null)

// 分页相关状态
const currentPage = ref(parseInt(route.query.page) || 1)
const pageSize = ref(10)
const totalCount = ref(0)
const paginatedConversations = ref([])
const isLoading = ref(true)

// 加载agents
const loadAgents = async () => {
  try {
    const agentList = await agentAPI.getAgents()
    agents.value = agentList || []
  } catch (error) {
    agents.value = []
  }
}

// 获取Agent头像
const getAgentAvatar = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  if (agent) {
    return `https://api.dicebear.com/9.x/bottts/svg?eyes=round,roundFrame01,roundFrame02&mouth=smile01,smile02,square01,square02&seed=${encodeURIComponent(agent.id)}`
  }
  return 'https://api.dicebear.com/9.x/bottts/svg?seed=default'
}

// 分页加载对话列表
const loadConversationsPaginated = async () => {
  try {
    isLoading.value = true
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchTerm.value || undefined,
      agent_id: filterAgent.value !== 'all' ? filterAgent.value : undefined,
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
  } catch (error) {
    toast.error(t('history.loadListFailed'))
    paginatedConversations.value = []
    totalCount.value = 0
  } finally {
    isLoading.value = false
  }
}

// 处理页码变化
const handlePageChange = (page) => {
  currentPage.value = page
}

// 处理每页大小变化
const handlePageSizeChange = (size) => {
  pageSize.value = size
  if (currentPage.value !== 1) {
    currentPage.value = 1 // 会触发 watch(currentPage)
  } else {
    loadConversationsPaginated()
  }
}

// Methods
const canDelete = (conversation) => {
  if (!currentUser.value) return false
  return currentUser.value.role === 'admin' || currentUser.value.id === conversation.user_id
}

const handleDeleteConversation = async (conversation) => {
  if (!confirm(t('history.deleteConfirm'))) return
  
  try {
    await chatAPI.deleteConversation(conversation.session_id)
    toast.success(t('history.deleteSuccess'))
    // 重新加载列表
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

// 格式化相对时间
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

const handleShareConversation = async (conversation) => {
  // 调用后端接口获取conversation的messages
  const response = await chatAPI.getConversationMessages(conversation.session_id)
  conversation.messages = response.messages || []
  shareConversation.value = conversation
  showShareModal.value = true
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
  } catch (e) {
    toast.error(t('history.copyFailed'))
  }
}

const formatMessageForExport = (messages) => {
  if (!messages || !Array.isArray(messages)) return []
  
  return messages.map(message => {
    if (message.role === 'user') {
      return {
        role: 'user',
        content: message.content
      }
    } else if (message.role === 'assistant') {
      if (message.tool_calls && message.tool_calls.length > 0) {
        return {
          role: 'assistant',
          tool_calls: message.tool_calls
        }
      } else if (message.content && message.content !== '' && message.content !== false) {
        return {
          role: 'assistant',
          content: message.content
        }
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
  if (!shareConversation.value) {
    console.log('❌ shareConversation 为空，退出函数')
    return
  }
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  exportToMarkdown(shareConversation.value, getAgentName(shareConversation.value.agent_id), visibleMessages)
  showShareModal.value = false
  toast.success(t('history.markdownExported'))
}

const handleExportToHTML = () => {
  if (!shareConversation.value) {
    console.log('❌ shareConversation 为空，退出函数')
    return
  }
  
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  exportToHTML(shareConversation.value, visibleMessages)
  showShareModal.value = false
  toast.success(t('history.htmlExported'))
}

// 更新 URL 参数
const updateUrlParams = () => {
  router.replace({
    query: {
      ...route.query,
      search: searchTerm.value || undefined,
      agent_id: filterAgent.value !== 'all' ? filterAgent.value : undefined,
      sort_by: sortBy.value,
      page: currentPage.value > 1 ? String(currentPage.value) : undefined
    }
  })
}

// 监听搜索、过滤和排序条件的变化
watch([searchTerm, filterAgent, sortBy], () => {
  if (currentPage.value !== 1) {
    currentPage.value = 1 // 会触发 watch(currentPage)
  } else {
    updateUrlParams()
    loadConversationsPaginated()
  }
}, { deep: true })

// 监听页码变化
watch(currentPage, () => {
  updateUrlParams()
  loadConversationsPaginated()
})

// 生命周期钩子
onMounted(async () => {
  currentUser.value = getCurrentUser()
  await loadAgents()
  await loadConversationsPaginated()
})
</script>

<style scoped>
/* 多行文本截断 */
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
