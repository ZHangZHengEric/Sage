<template>
  <div class="h-full flex flex-col p-6 bg-background">
    <div class="bg-background rounded-lg flex-1 flex flex-col min-h-0">
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
            <SelectTrigger class="w-[140px]">
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
            <SelectTrigger class="w-[140px]">
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
      
      <div class="flex-1 overflow-y-auto pr-2 space-y-3">
        <!-- 加载状态 -->
        <div v-if="isLoading" class="flex flex-col gap-4 p-4 items-center justify-center py-20">
          <Loader class="h-8 w-8 animate-spin text-primary" />
        </div>
        
        <div
          v-else-if="paginatedConversations.length > 0"
          v-for="conversation in paginatedConversations"
          :key="conversation.id"
          :class="[
            'group border rounded-lg p-0 transition-all hover:shadow-md hover:border-primary/50 bg-card text-card-foreground',
            { 'border-primary bg-primary/5': selectedConversations.has(conversation.id) }
          ]"
        >
          <div class="flex items-start gap-4 p-4">
            <div class="flex-1 min-w-0 cursor-pointer" @click="handleSelectConversation(conversation)">
              <div class="flex justify-between items-start mb-2">
                <h3 class="text-base font-semibold leading-none tracking-tight text-foreground truncate pr-2">{{ conversation.title }}</h3>
                
                <div class="flex items-center gap-4 text-xs text-muted-foreground shrink-0 flex-wrap sm:flex-nowrap">
                  <span class="flex items-center gap-1 font-mono bg-muted px-1.5 py-0.5 rounded max-w-[120px] sm:max-w-none truncate">
                    <span class="truncate">{{ conversation.session_id }}</span>
                    <button
                      class="inline-flex items-center justify-center h-4 w-4 hover:text-primary transition-colors shrink-0"
                      @click.stop="copySessionId(conversation)"
                      :title="t('common.copy') || '复制'"
                    >
                      <Copy :size="10" />
                    </button>
                  </span>
                  <span class="flex items-center gap-1 shrink-0">
                    <Calendar :size="12" />
                    {{ formatDate(conversation.updated_at) }}
                  </span>
                  <span class="flex items-center gap-1">
                    <Clock :size="12" />
                    {{ formatTime(conversation.updated_at) }}
                  </span>
                </div>
              </div>
       
              <div class="flex justify-end items-center">
                <div class="text-right">
                  <span class="text-xs font-medium text-primary">{{ getAgentName(conversation.agent_id) }}</span>
                </div>
              </div>
            </div>
            
            <div class="flex flex-col gap-2 shrink-0">
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-foreground"
                @click.stop="handleShareConversation(conversation)"
                :title="t('history.share')"
              >
                <Share class="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
        
        <div v-if="!isLoading && totalCount === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground min-h-[300px]">
          <MessageCircle :size="48" class="mb-4 opacity-50" />
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
          Previous
        </Button>
        <span class="text-sm text-muted-foreground">
          Page {{ currentPage }} of {{ Math.ceil(totalCount / pageSize) }}
        </span>
        <Button 
          variant="outline" 
          size="sm" 
          :disabled="currentPage * pageSize >= totalCount" 
          @click="handlePageChange(currentPage + 1)"
        >
          Next
        </Button>
      </div>
    </div>
    
    <!-- 分享模态框 -->
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
              {{ t('history.exportMarkdown') }}
            </Button>
            <Button
              class="flex-1"
              variant="outline"
              @click="handleExportToHTML"
            >
              {{ t('history.exportHTML') }}
            </Button>
          </div>
          <div class="mt-4 p-4 bg-muted/50 rounded-md text-sm">
            <p class="mb-2"><strong>{{ t('history.conversationTitle') }}</strong>: {{ shareConversation?.title }}</p>
            <p><strong>{{ t('history.messageCount') }}</strong>: {{ getVisibleMessageCount() }} {{ t('history.visibleMessages') }}</p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MessageCircle, Search, Calendar, User, Bot, Clock, Filter, Share, Copy, Loader } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useLanguage } from '@/utils/i18n.js'
import { exportToHTML, exportToMarkdown } from '@/utils/exporter.js'
import { agentAPI } from '@/api/agent.js'
import { chatAPI } from '@/api/chat.js'

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

// Define emits
const emit = defineEmits(['select-conversation'])

const router = useRouter()

// Get data from stores with null checks
const agents = ref([])
// Composables
const { t, language } = useLanguage()

// State
const searchTerm = ref('')
const filterAgent = ref('all')
const sortBy = ref('date')
const selectedConversations = ref(new Set())
const showShareModal = ref(false)
const shareConversation = ref(null)

// 分页相关状态
const currentPage = ref(1)
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
    paginatedConversations.value = response.list || []
    totalCount.value = response.total || 0
  } catch (error) {
    toast.error('加载对话列表失败')
    paginatedConversations.value = []
    totalCount.value = 0
  } finally {
    isLoading.value = false
  }
}

// 处理页码变化
const handlePageChange = (page) => {
  currentPage.value = page
  loadConversationsPaginated()
}

// 处理每页大小变化
const handlePageSizeChange = (size) => {
  pageSize.value = size
  currentPage.value = 1
  loadConversationsPaginated()
}

// Methods
const handleSelectConversation = (conversation) => {
  router.push({
    path: '/agent/chat',
    query: {
      session_id: conversation.session_id
    }
  })
}

const formatDate = (timestamp) => {
  const date = new Date(timestamp)
  const now = new Date()
  const diffTime = Math.abs(now - date)
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
  
  if (diffDays === 1) {
    return t('history.today')
  } else if (diffDays === 2) {
    return t('history.yesterday')
  } else if (diffDays <= 7) {
    return t('history.daysAgo').replace('{days}', diffDays - 1)
  } else {
    const locale = language.value === 'en-US' ? 'en-US' : 'zh-CN'
    return date.toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }
}

const formatTime = (timestamp) => {
  const locale = language.value === 'en-US' ? 'en-US' : 'zh-CN'
  return new Date(timestamp).toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit'
  })
}


const getAgentName = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  return agent ? agent.name : '未知Agent'
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
      toast.success('session_id已复制')
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
    toast.success('session_id已复制')
  } catch (e) {
    toast.error('复制失败')
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
      } else if (message.show_content && message.show_content !== '' && message.show_content !== false) {
        return {
          role: 'assistant',
          show_content: message.show_content
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
    msg.role === 'user' || (msg.role === 'assistant' && msg.message_type !== 'token_usage' && msg.show_content && msg.show_content !== '' && msg.show_content !== false)
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
  toast.success('Markdown文件已导出')
}

const handleExportToHTML = () => {
  if (!shareConversation.value) {
    console.log('❌ shareConversation 为空，退出函数')
    return
  }
  
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  exportToHTML(shareConversation.value, visibleMessages)
  showShareModal.value = false
  toast.success('HTML文件已导出')
}

// 监听搜索、过滤和排序条件的变化
watch([searchTerm, filterAgent, sortBy], () => {
  currentPage.value = 1 // 重置到第一页
  loadConversationsPaginated()
}, { deep: true })

// 生命周期钩子
onMounted(async () => {
  await loadAgents()
  await loadConversationsPaginated()
})
</script>