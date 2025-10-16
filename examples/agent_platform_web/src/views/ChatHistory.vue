<template>
  <div class="history-page">
    <div class="page-header">
      <div class="page-title">
        <h2>{{ t('history.title') }}</h2>
        <p>{{ t('history.subtitle') }}</p>
      </div>
      
      <div class="history-stats">
        <div class="stat-item">
          <span class="stat-number">{{ conversationsCount }}</span>
          <span class="stat-label">{{ t('history.totalConversations') }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-number">{{ totalMessages }}</span>
          <span class="stat-label">{{ t('history.totalMessages') }}</span>
        </div>
      </div>
    </div>
    
    <div class="history-controls">
      <div class="search-filter-row">
        <div class="search-box">
          <Search :size="16" class="search-icon" />
          <el-input
            v-model="searchTerm"
            :placeholder="t('history.search')"
            class="search-input"
          />
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
          
          <el-button
            v-if="conversationsCount > 0"
            type="danger"
            @click="handleDeleteAll"
          >
            <Trash2 :size="16" />
            {{ t('history.clearAll') }}
          </el-button>
        </div>
      </div>
      
      <div v-if="selectedConversations.size > 0" class="bulk-actions">
        <span class="selected-count">
          {{ t('history.selectedCount') }} {{ selectedConversations.size }} 个对话
        </span>
        <el-button type="danger" @click="handleDeleteSelected">
          <Trash2 :size="16" />
          {{ t('history.deleteSelected') }}
        </el-button>
      </div>
    </div>
    
    <div class="conversations-container">
      <div class="conversations-list">
        <div
          v-for="conversation in filteredConversations"
          :key="conversation.id"
          :class="['conversation-card', { selected: selectedConversations.has(conversation.id) }]"
        >
          <div class="conversation-header">
            <div class="conversation-select">
              <el-checkbox
                :model-value="selectedConversations.has(conversation.id)"
                @change="handleSelectConversation(conversation.id)"
                @click.stop
              />
            </div>
            
            <div class="conversation-info" @click="$emit('select-conversation', conversation)">
              <div class="conversation-title-row">
                <h3 class="conversation-title">{{ conversation.title }}</h3>
                <div class="conversation-meta">
                  <span class="conversation-date">
                    <Calendar :size="12" />
                    {{ formatDate(conversation.updatedAt) }}
                  </span>
                  <span class="conversation-time">
                    <Clock :size="12" />
                    {{ formatTime(conversation.updatedAt) }}
                  </span>
                </div>
              </div>
              
              <p class="conversation-preview">
                {{ getConversationPreview(conversation.messages) }}
              </p>
              
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
                  <span class="agent-name">{{ getAgentName(conversation.agentId) }}</span>
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
              <el-button
                type="danger"
                size="small"
                @click.stop="handleDeleteConversation(conversation)"
                :title="t('history.delete')"
              >
                <Trash2 :size="16" />
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <div v-if="filteredConversations.length === 0 && conversationsCount > 0" class="empty-state">
      <Filter :size="48" class="empty-icon" />
      <h3>{{ t('history.noMatchingConversations') }}</h3>
      <p>{{ t('history.noMatchingDesc') }}</p>
    </div>
    
    <div v-if="conversationsCount === 0" class="empty-state">
      <MessageCircle :size="48" class="empty-icon" />
      <h3>{{ t('history.noConversations') }}</h3>
      <p>{{ t('history.noConversationsDesc') }}</p>
      <el-button type="primary" @click="$emit('select-conversation', null)">
        {{ t('history.startNewChat') }}
      </el-button>
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
            @click="exportToMarkdown"
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
import { ref, computed, onMounted } from 'vue'
import { MessageCircle, Search, Trash2, Calendar, User, Bot, Clock, Filter, Share } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useLanguage } from '../utils/language.js'
import { exportToHTML } from '../utils/htmlExporter.js'
import { useChatStore } from '../stores/index.js'
import { agentAPI } from '../api/index.js'

// Stores
const chatStore = useChatStore()

// Get data from stores with null checks
const conversations = computed(() => chatStore.conversations || [])
const agents = ref([])

// 加载agents
const loadAgents = async () => {
  try {
    const agentList = await agentAPI.getAgents()
    agents.value = agentList || []
  } catch (error) {
    console.error('加载agents失败:', error)
    agents.value = []
  }
}

// Emits
const emit = defineEmits(['delete-conversation', 'select-conversation'])

// Composables
const { t, language } = useLanguage()

// State
const searchTerm = ref('')
const filterAgent = ref('all')
const sortBy = ref('date')
const selectedConversations = ref(new Set())
const showShareModal = ref(false)
const shareConversation = ref(null)

// Computed
const conversationsCount = computed(() => {
  return conversations.value?.length || 0
})

const totalMessages = computed(() => {
  return conversations.value.reduce((sum, conv) => sum + (conv.messages?.length || 0), 0)
})

const filteredConversations = computed(() => {
  return conversations.value
    .filter(conv => {
      const matchesSearch = conv.title.toLowerCase().includes(searchTerm.value.toLowerCase()) ||
                           getConversationPreview(conv.messages).toLowerCase().includes(searchTerm.value.toLowerCase())
      const matchesAgent = filterAgent.value === 'all' || conv.agentId === filterAgent.value
      return matchesSearch && matchesAgent
    })
    .sort((a, b) => {
      switch (sortBy.value) {
        case 'date':
          return new Date(b.updatedAt) - new Date(a.updatedAt)
        case 'title':
          return a.title.localeCompare(b.title)
        case 'messages':
          return (b.messages?.length || 0) - (a.messages?.length || 0)
        default:
          return 0
      }
    })
})

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

const getConversationPreview = (messages) => {
  if (!messages || messages.length === 0) {
    return t('history.noMessages')
  }
  
  const userMessages = messages.filter(msg => msg.role === 'user')
  if (userMessages.length === 0) {
    return t('history.noUserMessages')
  }
  
  const firstUserMessage = userMessages[0].content || ''
  return firstUserMessage.length > 100 
    ? firstUserMessage.substring(0, 100) + '...' 
    : firstUserMessage
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

const handleSelectConversation = (convId) => {
  const newSelected = new Set(selectedConversations.value)
  if (newSelected.has(convId)) {
    newSelected.delete(convId)
  } else {
    newSelected.add(convId)
  }
  selectedConversations.value = newSelected
}

const handleDeleteSelected = async () => {
  try {
    await ElMessageBox.confirm(
      t('history.deleteSelectedConfirm').replace('{count}', selectedConversations.value.size),
      t('common.confirm'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      }
    )
    
    selectedConversations.value.forEach(convId => {
      emit('delete-conversation', convId)
    })
    selectedConversations.value = new Set()
  } catch {
    // User cancelled
  }
}

const handleDeleteAll = async () => {
  try {
    await ElMessageBox.confirm(
      '确定要删除所有对话记录吗？此操作不可恢复。',
      t('common.confirm'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      }
    )
    
    conversations.value.forEach(conv => {
      emit('delete-conversation', conv.id)
    })
  } catch {
    // User cancelled
  }
}

const handleDeleteConversation = async (conversation) => {
  try {
    await ElMessageBox.confirm(
      t('history.deleteConfirm'),
      t('common.confirm'),
      {
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      }
    )
    
    emit('delete-conversation', conversation.id)
  } catch {
    // User cancelled
  }
}

const handleShareConversation = (conversation) => {
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
    msg.role === 'user' || (msg.role === 'assistant' && msg.show_content && msg.show_content !== '' && msg.show_content !== false)
  ).length
}

const exportToMarkdown = () => {
  if (!shareConversation.value) return
  
  const visibleMessages = formatMessageForExport(shareConversation.value.messages)
  
  let markdown = `# ${shareConversation.value.title}\n\n`
  markdown += `**导出时间**: ${new Date().toLocaleString()}\n`
  markdown += `**Agent**: ${getAgentName(shareConversation.value.agentId)}\n`
  markdown += `**消息数量**: ${visibleMessages.length}\n\n`
  markdown += '---\n\n'
  
  visibleMessages.forEach((message, index) => {
    if (message.role === 'user') {
      markdown += `## 用户 ${index + 1}\n\n${message.content}\n\n`
    } else if (message.role === 'assistant') {
      if (message.show_content) {
        markdown += `## 助手 ${index + 1}\n\n${message.show_content}\n\n`
      } else if (message.tool_calls) {
        markdown += `## 助手 ${index + 1} (工具调用)\n\n`
        message.tool_calls.forEach(tool => {
          markdown += `**工具**: ${tool.function.name}\n`
          markdown += `**参数**: \`\`\`json\n${JSON.stringify(tool.function.arguments, null, 2)}\n\`\`\`\n\n`
        })
      }
    }
  })
  
  // 下载文件
  const blob = new Blob([markdown], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${shareConversation.value.title}_${new Date().toISOString().split('T')[0]}.md`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
  
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

// 生命周期钩子
onMounted(async () => {
  await loadAgents()
})
</script>

<style scoped>
.history-page {
  padding: 1.5rem;
  background: var(--bg-primary);
  min-height: 100vh;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
}

.page-title h2 {
  margin: 0 0 0.5rem 0;
  color: var(--text-primary);
  font-size: 1.5rem;
  font-weight: 600;
}

.page-title p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.history-stats {
  display: flex;
  gap: 2rem;
}

.stat-item {
  text-align: center;
}

.stat-number {
  display: block;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--primary-color);
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.history-controls {
  margin-bottom: 1.5rem;
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
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-secondary);
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
  background: var(--warning-bg);
  border: 1px solid var(--warning-color);
  border-radius: 6px;
  margin-bottom: 1rem;
}

.selected-count {
  color: var(--warning-color);
  font-weight: 500;
}

.conversations-container {
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.conversations-list {
  padding: 1rem;
}

.conversation-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  margin-bottom: 1rem;
  background: var(--bg-primary);
  transition: all 0.2s ease;
}

.conversation-card:hover {
  border-color: var(--primary-color);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.conversation-card.selected {
  border-color: var(--primary-color);
  background: var(--primary-bg);
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
  color: var(--text-primary);
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
  color: var(--text-secondary);
}

.conversation-preview {
  margin: 0 0 1rem 0;
  color: var(--text-secondary);
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
  color: var(--text-secondary);
}

.agent-info {
  text-align: right;
}

.agent-name {
  font-size: 0.75rem;
  color: var(--primary-color);
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
  color: var(--text-secondary);
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
  background: var(--bg-tertiary);
  border-radius: 6px;
  font-size: 0.875rem;
}

.export-info p {
  margin: 0.5rem 0;
}

@media (max-width: 768px) {
  .history-page {
    padding: 1rem;
  }
  
  .page-header {
    flex-direction: column;
    gap: 1rem;
    align-items: stretch;
  }
  
  .history-stats {
    justify-content: space-around;
  }
  
  .search-filter-row {
    flex-direction: column;
    align-items: stretch;
  }
  
  .filter-controls {
    justify-content: space-between;
  }
  
  .conversation-title-row {
    flex-direction: column;
    gap: 0.5rem;
  }
  
  .conversation-meta {
    justify-content: flex-start;
  }
  
  .conversation-stats {
    flex-direction: column;
    gap: 0.5rem;
    align-items: flex-start;
  }
  
  .conversation-actions {
    flex-direction: row;
  }
}
</style>