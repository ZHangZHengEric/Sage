<template>
  <div class="history-page">
    <div class="conversations-container">
      <div class="search-filter-row">
        <div class="search-box">
          <el-input
            v-model="searchTerm"
            :placeholder="t('history.search')"
            class="search-input"
          />
        <Search :size="16" class="search-icon" />
        </div>
        
        <div class="filter-controls">
          <el-select v-model="filterAgent" class="filter-select">
            <el-option :label="t('history.all')" value="all" />
            <el-option
              v-for="agent in agents"
              :key="agent.id"
              :label="agent.name"
              :value="agent.id"
            />
          </el-select>
          
          <el-select v-model="sortBy" class="sort-select">
            <el-option :label="t('history.sortByDate')" value="date" />
            <el-option :label="t('history.sortByTitle')" value="title" />
            <el-option :label="t('history.sortByMessages')" value="messages" />
          </el-select>
          

        </div>
      </div>
      <div class="conversations-list">
        <!-- 加载状态 -->
        <div v-if="isLoading" class="loading-state">
        </div>
        <div
          v-else
          v-for="conversation in paginatedConversations"
          :key="conversation.id"
          :class="['conversation-card', { selected: selectedConversations.has(conversation.id) }]"
        >
          <div class="conversation-header">
            <div class="conversation-info" @click="$emit('select-conversation', conversation)">
              <div class="conversation-title-row">
                <h3 class="conversation-title">{{ conversation.title }}</h3>
                <div class="conversation-meta">
                  <span class="conversation-date">
                    <Calendar :size="12" />
                    {{ formatDate(conversation.updated_at) }}
                  </span>
                  <span class="conversation-time">
                    <Clock :size="12" />
                    {{ formatTime(conversation.updated_at) }}
                  </span>
                </div>
              </div>
       
              <div class="conversation-stats">
                <div class="stat-group">
                  <div class="stat-item-small">
                    <User :size="12" />
                    <span>{{ getMessageCount(conversation.messages).user }}</span>
                  </div>
                  <div class="stat-item-small">
                    <Bot :size="12" />
                    <span>{{ getMessageCount(conversation.messages).assistant }}</span>
                  </div>
                </div>
                
                <div class="agent-info">
                  <span class="agent-name">{{ getAgentName(conversation.agent_id) }}</span>
                </div>
              </div>
            </div>
            
            <div class="conversation-actions">
              <el-button
                type="primary"
                size="small"
                @click.stop="handleShareConversation(conversation)"
                :title="t('history.share')"
              >
                <Share :size="16" />
              </el-button>
            </div>
          </div>
        </div>
      </div>
          
    <!-- 分页组件 -->
    <div v-if="totalCount > 0" class="pagination-container">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[5, 10, 20, 50]"
        :total="totalCount"
        :background="true"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />
    </div>
    </div>

    <div v-if="totalCount === 0" class="empty-state">
      <MessageCircle :size="48" class="empty-icon" />
      <h3>{{ t('history.noConversations') }}</h3>
      <p>{{ t('history.noConversationsDesc') }}</p>
    </div>
    
    <!-- 分享模态框 -->
    <el-dialog
      v-model="showShareModal"
      :title="t('history.shareTitle')"
      width="500px"
    >
      <div class="modal-body">
        <p>{{ t('history.exportFormat') }}</p>
        <div class="export-options">
          <el-button
            type="primary"
            class="export-btn"
            @click="handleExportToMarkdown"
          >
            {{ t('history.exportMarkdown') }}
          </el-button>
          <el-button
            class="export-btn"
            @click="handleExportToHTML"
          >
            {{ t('history.exportHTML') }}
          </el-button>
        </div>
        <div class="export-info">
          <p><strong>{{ t('history.conversationTitle') }}</strong>{{ shareConversation?.title }}</p>
          <p><strong>{{ t('history.messageCount') }}</strong>{{ getVisibleMessageCount() }} {{ t('history.visibleMessages') }}</p>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { MessageCircle, Search, Calendar, User, Bot, Clock, Filter, Share } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { useLanguage } from '../utils/i18n.js'
import { exportToHTML, exportToMarkdown } from '../utils/exporter.js'
import { agentAPI } from '../api/agent.js'
import { chatAPI } from '../api/chat.js'

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
const isLoading = ref(false)

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
      sort_by: sortBy.value
    }
    const response = await chatAPI.getConversationsPaginated(params)
    paginatedConversations.value = response.list || []
    totalCount.value = response.total || 0
    // 循环加载messages
    for (const conversation of paginatedConversations.value) {
        // 调用后端接口获取conversation的messages
        const response = await chatAPI.getConversationMessages(conversation.session_id)
        conversation.messages = response.messages || []
    }
  } catch (error) {
    ElMessage.error('加载对话列表失败')
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

const getMessageCount = (messages) => {
  if (!messages) return { user: 0, assistant: 0 }
  
  return messages.reduce((count, msg) => {
    if (msg.role === 'user') count.user++
    else if (msg.role === 'assistant') count.assistant++
    return count
  }, { user: 0, assistant: 0 })
}

const getAgentName = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  return agent ? agent.name : '未知Agent'
}

const handleShareConversation = async (conversation) => {
  shareConversation.value = conversation
  showShareModal.value = true
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
  ElMessage.success('Markdown文件已导出')
}

const handleExportToHTML = () => {
  if (!shareConversation.value) {
    console.log('❌ shareConversation 为空，退出函数')
    return
  }
  
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  exportToHTML(shareConversation.value, visibleMessages)
  showShareModal.value = false
  ElMessage.success('HTML文件已导出')
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

<style scoped>
.history-page {
  padding: 1.5rem;
  min-height: 100vh;
  background: transparent;
}

.conversations-container {
  background: transparent;
  border-radius: 8px;
}

.search-filter-row {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1rem;
}

.search-box {
  position: relative;
  flex: 1;
  max-width: 400px;
}

.search-icon {
  position: absolute;
  left: 1rem;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(0, 0, 0, 1);
  z-index: 1;
}

.search-input {
  padding-left: 2.5rem;
}

.filter-controls {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.filter-select,
.sort-select {
  min-width: 120px;
}

.bulk-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  background: rgba(255, 193, 7, 0.1);
  border: 1px solid #ffc107;
  border-radius: 6px;
  margin-bottom: 1rem;
}

.selected-count {
  color: #ffc107;
  font-weight: 500;
}



.conversations-list {
  padding: 1rem;
    overflow-y: auto;
  max-height: calc(100vh - 200px);
}

.loading-state {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
}

.conversation-card {
  border: 1px solid rgba(159, 147, 147, 0.328);
  border-radius: 8px;
  margin-bottom: 1rem;
  background: transparent;
  transition: all 0.2s ease;
}

.conversation-card:hover {
  border-color: #667eea;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.conversation-card.selected {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.1);
}

.conversation-header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem;
}

.conversation-select {
  padding-top: 0.25rem;
}

.conversation-info {
  flex: 1;
  cursor: pointer;
  min-width: 0;
}

.conversation-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 0.5rem;
}

.conversation-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1d1d1d;
  word-break: break-word;
}

.conversation-meta {
  display: flex;
  gap: 1rem;
  align-items: center;
  flex-shrink: 0;
}

.conversation-date,
.conversation-time {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: rgba(72, 65, 65, 0.7);
}

.conversation-preview {
  margin: 0 0 1rem 0;
  color: rgba(100, 84, 84, 0.7);
  font-size: 0.875rem;
  line-height: 1.4;
  word-break: break-word;
}

.conversation-stats {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-group {
  display: flex;
  gap: 1rem;
}

.stat-item-small {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: rgba(82, 74, 74, 0.7);
}

.agent-info {
  text-align: right;
}

.agent-name {
  font-size: 0.75rem;
  color: #667eea;
  font-weight: 500;
}

.conversation-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex-shrink: 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 3rem 2rem;
  color: rgba(255, 255, 255, 0.7);
}

.empty-icon {
  margin-bottom: 1rem;
  opacity: 0.5;
}

.empty-state h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1.125rem;
  font-weight: 500;
}

.empty-state p {
  margin: 0 0 1.5rem 0;
  font-size: 0.875rem;
}

.export-options {
  display: flex;
  gap: 1rem;
  margin: 1rem 0;
}

.export-btn {
  flex: 1;
}

.export-info {
  margin-top: 1rem;
  padding: 1rem;
  background: transparent;
  border-radius: 6px;
  font-size: 0.875rem;
}

.export-info p {
  margin: 0.5rem 0;
}

/* 分页样式 */
.pagination-container {
  display: flex;
  justify-content: center;
  margin: 2rem 0;
  padding: 1rem;
  border-radius: 8px;
}

.pagination-container :deep(.el-pagination) {
  --el-pagination-bg-color: transparent;
  --el-pagination-border-radius: 6px;
}

.pagination-container :deep(.el-pagination .btn-prev),
.pagination-container :deep(.el-pagination .btn-next) {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color:  #1a1a2e;
}

.pagination-container :deep(.el-pagination .btn-prev:hover),
.pagination-container :deep(.el-pagination .btn-next:hover) {
  background: rgba(255, 255, 255, 0.05);
}

.pagination-container :deep(.el-pagination .el-pager li) {
  background: #1a1a2e;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #ffffff;
  margin: 0 2px;
}

.pagination-container :deep(.el-pagination .el-pager li:hover) {
  background: rgba(255, 255, 255, 0.05);
}

.pagination-container :deep(.el-pagination .el-pager li.is-active) {
  background: transparent;
  color: #1a1a2e;
}
</style>