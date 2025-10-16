<template>
  <div class="chat-page">
    <div class="chat-header">
      <div class="chat-title">
        <h2>{{ t('chat.title') }}</h2>
        <span v-if="selectedAgent" class="agent-name">
          {{ t('chat.current') }}: {{ selectedAgent.name }}
        </span>
      </div>
      <div class="chat-controls">
        <el-select 
          v-model="selectedAgentId"
          class="agent-select"
          @change="handleAgentChange"
        >
          <el-option
            v-for="agent in (agents || [])"
            :key="agent.id"
            :label="agent.name"
            :value="agent.id"
          />
        </el-select>
      </div>
    </div>
    
    <div :class="['chat-container', { 'split-view': showToolDetails || showTaskStatus || showWorkspace || showSettings }]">
      <div class="chat-messages">
        <div v-if="!messages || messages.length === 0" class="empty-state">
          <Bot :size="48" class="empty-icon" />
          <h3>{{ t('chat.emptyTitle') }}</h3>
          <p>{{ t('chat.emptyDesc') }}</p>
        </div>
        <div v-else class="messages-list">
          <MessageRenderer
            v-for="(message, index) in (messages || [])"
            :key="message.id || index"
            :message="message"
            :messages="messages || []"
            :message-index="index"
            @download-file="downloadFile"
            @tool-click="handleToolClick"
          />
          <div v-if="isLoading" class="loading-indicator">
            <div class="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>
        <div ref="messagesEndRef" />
      </div>
      
      <div v-if="showToolDetails && selectedToolExecution" class="tool-details-panel">
        <div class="tool-details-header">
          <h3>{{ t('chat.toolDetails') }}</h3>
          <el-button 
            type="text"
            @click="showToolDetails = false"
          >
            ×
          </el-button>
        </div>
        <div class="tool-details-content">
          <div class="tool-section">
            <h4>{{ t('chat.toolName') }}</h4>
            <p>{{ selectedToolExecution.name }}</p>
          </div>
          <div class="tool-section">
            <h4>{{ t('chat.toolParams') }}</h4>
            <pre class="tool-code">{{ JSON.stringify(selectedToolExecution.arguments, null, 2) }}</pre>
          </div>
          <div class="tool-section">
            <h4>{{ t('chat.toolResult') }}</h4>
            <pre class="tool-code">{{ formatToolResult(selectedToolExecution.result) }}</pre>
          </div>
        </div>
      </div>
      

      
      <ConfigPanel
        v-if="showSettings"
        :agents="agents"
        :selected-agent="selectedAgent"
        :config="config"
        @agent-select="selectAgent"
        @config-change="updateConfig"
        @close="showSettings = false"
      />
    </div>
    
    <MessageInput
      :is-loading="isLoading"
      @send-message="handleSendMessage"
      @stop-generation="handleStopGeneration"
    />
  </div>
</template>

<script setup>
import { ref, computed, reactive, watch, onMounted, nextTick, defineExpose } from 'vue'
import { Bot, Settings, List, Folder } from 'lucide-vue-next'
import { useToolStore, useChatStore, useAppStore } from '../stores/index.js'
import { chatAPI, agentAPI } from '../api/index.js'
import { taskAPI } from '../api/index.js'
import { zhCN, enUS } from '../utils/i18n.js'
import MessageRenderer from '../components/chat/MessageRenderer.vue'
import ConfigPanel from '../components/chat/ConfigPanel.vue'
import MessageInput from '../components/chat/MessageInput.vue'

// Stores
const toolStore = useToolStore()
const chatStore = useChatStore()
const appStore = useAppStore()

// Props (保留selectedConversation用于兼容性)
const props = defineProps({
  selectedConversation: {
    type: Object,
    default: null
  }
})

// Emits
const emit = defineEmits(['add-conversation', 'update-conversation', 'clear-selected-conversation'])

// 从store获取数据
const tools = computed(() => toolStore.tools || [])

// ===== Language Composable (内联) =====
const translations = {
  zhCN: zhCN,
  enUS: enUS
}

const currentTranslation = computed(() => {
  return translations[appStore.language] || translations.zhCN
})

const t = (key, params = {}) => {
  const translation = currentTranslation.value
  let text = translation[key] || key
  
  if (params && typeof params === 'object') {
    Object.keys(params).forEach(param => {
      const regex = new RegExp(`\\{${param}\\}`, 'g')
      text = text.replace(regex, params[param])
    })
  }
  
  return text
}

// ===== Messages Composable (内联) =====
const messages = ref([])
const messageChunks = reactive({})
const isLoading = ref(false)
const inputMessage = ref('')
const abortControllerRef = ref(null)

const handleChunkMessage = (data) => {
  console.log('🧩 处理消息块:', data)
  
  const messageId = data.message_id
  if (!messageId) {
    console.warn('消息块缺少message_id')
    return
  }

  if (data.chunk_type === 'start') {
    messageChunks[messageId] = {
      chunks: [],
      isComplete: false,
      messageId: messageId
    }
    console.log(`🚀 开始收集消息块 ${messageId}`)
  } else if (data.chunk_type === 'data') {
    if (messageChunks[messageId]) {
      messageChunks[messageId].chunks.push(data.content || '')
      console.log(`📝 收集消息块数据 ${messageId}:`, data.content)
    }
  } else if (data.chunk_type === 'end') {
    if (messageChunks[messageId]) {
      const fullContent = messageChunks[messageId].chunks.join('')
      console.log(`🔗 重组完整消息 ${messageId}:`, fullContent)
      
      try {
        const messageData = JSON.parse(fullContent)
        console.log(`✅ 成功解析消息 ${messageId}:`, messageData)
        handleMessage(messageData)
      } catch (error) {
        console.error(`❌ 解析消息失败 ${messageId}:`, error, '原始内容:', fullContent)
      }
      
      delete messageChunks[messageId]
    }
  }
}

const handleMessage = (data) => {
  console.log('📨 处理消息:', data)
  
  if (!data.message_id) {
    console.warn('消息缺少message_id')
    return
  }

  const existingIndex = messages.value.findIndex(msg => msg.message_id === data.message_id)
  
  if (existingIndex !== -1) {
    const existingMessage = messages.value[existingIndex]
    
    if (data.role === 'tool') {
      messages.value[existingIndex] = { ...data }
      console.log(`🔄 更新工具消息 ${data.message_id}`)
    } else {
      const updatedMessage = { ...existingMessage, ...data }
      
      if (data.content && existingMessage.content) {
        updatedMessage.content = existingMessage.content + data.content
      }
      if (data.show_content && existingMessage.show_content) {
        updatedMessage.show_content = existingMessage.show_content + data.show_content
      }
      
      messages.value[existingIndex] = updatedMessage
      console.log(`🔄 更新消息 ${data.message_id}`)
    }
  } else {
    messages.value.push({ ...data })
    console.log(`➕ 添加新消息 ${data.message_id}`)
  }
}

const addUserMessage = (content) => {
  const userMessage = {
    message_id: `user_${Date.now()}`,
    role: 'user',
    content: content,
    timestamp: new Date().toISOString()
  }
  messages.value.push(userMessage)
  console.log('👤 添加用户消息:', userMessage)
}

const addErrorMessage = (error) => {
  const errorMessage = {
    message_id: `error_${Date.now()}`,
    role: 'assistant',
    content: `错误: ${error.message || error}`,
    show_content: `错误: ${error.message || error}`,
    timestamp: new Date().toISOString(),
    isError: true
  }
  messages.value.push(errorMessage)
  console.log('❌ 添加错误消息:', errorMessage)
}

const clearMessages = () => {
  messages.value = []
  Object.keys(messageChunks).forEach(key => {
    delete messageChunks[key]
  })
  console.log('🗑️ 清空所有消息')
}

const setMessages = (newMessages) => {
  messages.value = newMessages
}

const setIsLoading = (loading) => {
  isLoading.value = loading
}

// ===== Session Composable (内联) =====
const currentSessionId = ref(null)
const selectedAgent = ref(null)
const config = reactive({
  deepThinking: true,
  multiAgent: true,
  moreSuggest: false,
  maxLoopCount: 10
})
const userConfigOverrides = reactive({})

const createSession = () => {
  const sessionId = `session_${Date.now()}`
  currentSessionId.value = sessionId
  return sessionId
}

const clearSession = () => {
  currentSessionId.value = null
}

const updateConfig = (newConfig) => {
  console.log('🔧 updateConfig被调用，newConfig:', newConfig)
  console.log('🔧 当前config状态:', config)
  
  Object.assign(config, newConfig)
  console.log('🔧 更新后的config:', config)
  
  Object.assign(userConfigOverrides, newConfig)
  console.log('🔧 更新后的userConfigOverrides:', userConfigOverrides)
}

const selectAgent = (agent, forceConfigUpdate = false) => {
  const isAgentChange = !selectedAgent.value || selectedAgent.value.id !== agent?.id
  selectedAgent.value = agent
  
  if (agent && (isAgentChange || forceConfigUpdate)) {
    Object.assign(config, {
      deepThinking: userConfigOverrides.deepThinking !== undefined 
        ? userConfigOverrides.deepThinking 
        : agent.deepThinking,
      multiAgent: userConfigOverrides.multiAgent !== undefined 
        ? userConfigOverrides.multiAgent 
        : agent.multiAgent,
      moreSuggest: userConfigOverrides.moreSuggest !== undefined 
        ? userConfigOverrides.moreSuggest 
        : (agent.moreSuggest ?? false),
      maxLoopCount: userConfigOverrides.maxLoopCount !== undefined 
        ? userConfigOverrides.maxLoopCount 
        : (agent.maxLoopCount ?? 10)
    })
  }
}

const loadSession = (sessionId) => {
  currentSessionId.value = sessionId
}

const saveSession = (sessionId, data) => {
  // 这里可以实现会话保存逻辑
  console.log('💾 保存会话:', sessionId, data)
}

// ===== Task Manager Composable (内联) =====
const taskStatus = ref(null)
const workspaceFiles = ref([])
const workspacePath = ref(null)
const expandedTasks = reactive(new Set())
const lastMessageId = ref(null)

const fetchTaskStatus = async (sessionId) => {
  if (!sessionId) return
  
  console.log('🔄 开始请求任务状态, sessionId:', sessionId)
  
  try {
    const data = await taskAPI.getTaskStatus(sessionId)
    console.log('📊 任务状态响应数据:', data)
    const tasksObj = data.tasks_status?.tasks || {}
    console.log('📊 任务对象:', tasksObj)
    const tasks = Object.values(tasksObj)
    console.log('📊 任务数组:', tasks)
    tasks.forEach((task, index) => {
      console.log(`📊 任务${index + 1}详细数据:`, task)
      if (task.execution_summary) {
        console.log(`📊 任务${index + 1} execution_summary:`, task.execution_summary)
      }
    })
    taskStatus.value = tasks
    console.log('✅ 任务状态请求成功, 任务数量:', tasks.length)
  } catch (error) {
    console.error('获取任务状态出错:', error)
  }
}

const fetchWorkspaceFiles = async (sessionId) => {
  if (!sessionId) return
  
  console.log('📁 开始请求工作空间文件, sessionId:', sessionId)
  
  try {
    const data = await taskAPI.getWorkspaceFiles(sessionId)
    console.log('📁 工作空间文件原始数据:', data)
    console.log('📁 工作空间文件数组:', data.files)
    workspaceFiles.value = data.files || []
    workspacePath.value = data.agent_workspace
    console.log('✅ 工作空间文件请求成功, 文件数量:', data.files?.length || 0)
  } catch (error) {
    console.error('获取工作空间文件出错:', error)
  }
}

const downloadFile = async (filePath) => {
  try {
    const blob = await taskAPI.downloadFile(filePath, workspacePath.value)
    
    const blobUrl = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.style.display = 'none'
    a.href = blobUrl
    a.download = filePath.split('/').pop()
    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(blobUrl)
    document.body.removeChild(a)
  } catch (error) {
    console.error('下载文件出错:', error)
  }
}

// ===== Chat API Composable (内联) =====
const abortController = ref(null)

const sendMessage = async (
  message,
  sessionId,
  config,
  selectedAgent,
  onChunkMessage,
  onMessage
) => {
  try {
    abortController.value = new AbortController()

    const requestBody = {
      message: message,
      session_id: sessionId,
      agent_config: {
        deep_thinking: config.deepThinking,
        multi_agent: config.multiAgent,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount,
        system_context: selectedAgent?.systemContext || '',
        workflows: selectedAgent?.workflows || [],
        llm_config: selectedAgent?.llmConfig || {},
        system_prefix: selectedAgent?.systemPrefix || '',
        available_tools: selectedAgent?.availableTools || []
      }
    }

    console.log('🚀 发送消息请求:', requestBody)

    const response = await chatAPI.sendMessageStream(requestBody, {
      signal: abortController.value.signal
    })

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.trim()) {
          try {
            const data = JSON.parse(line)
            console.log('📨 收到流式数据:', data)
            
            if (data.type === 'chunk') {
              onChunkMessage && onChunkMessage(data)
            } else {
              onMessage && onMessage(data)
            }
          } catch (parseError) {
            console.error('解析JSON失败:', parseError, '原始数据:', line)
          }
        }
      }
    }

    if (buffer.trim()) {
      try {
        const data = JSON.parse(buffer)
        console.log('📨 收到最后的流式数据:', data)
        
        if (data.type === 'chunk') {
          onChunkMessage && onChunkMessage(data)
        } else {
          onMessage && onMessage(data)
        }
      } catch (parseError) {
        console.error('解析最后的JSON失败:', parseError, '原始数据:', buffer)
      }
    }

  } catch (error) {
    if (error.name === 'AbortError') {
      console.log('请求被中止')
    } else {
      console.error('发送消息失败:', error)
      throw error
    }
  } finally {
    abortController.value = null
  }
}

const interruptSession = async (sessionId) => {
  try {
    await chatAPI.interruptSession(sessionId)
    console.log('✅ 会话中断成功')
  } catch (error) {
    console.error('中断会话失败:', error)
    throw error
  }
}

// ===== Component State =====
const selectedAgentId = computed({
  get: () => selectedAgent.value?.id || '',
  set: (value) => {
    const agent = agents.value.find(a => a.id === value)
    selectAgent(agent)
  }
})

const showSettings = ref(false)
const showToolDetails = ref(false)
const showTaskStatus = ref(false)
const showWorkspace = ref(false)
const selectedToolExecution = ref(null)
const messagesEndRef = ref(null)

// ===== Component Methods =====
const handleAgentChange = (agentId) => {
  const agent = agents.value.find(a => a.id === agentId)
  selectAgent(agent)
}

const handleToolClick = (toolExecution) => {
  selectedToolExecution.value = toolExecution
  showToolDetails.value = true
}

const handleStopGeneration = async () => {
  console.log('🛑 停止生成请求')
  
  if (abortControllerRef.value) {
    abortControllerRef.value.abort()
    abortControllerRef.value = null
    console.log('🛑 中止HTTP请求')
  }
  
  if (currentSessionId.value) {
    try {
      await interruptSession(currentSessionId.value)
      console.log('🛑 后端会话中断成功')
    } catch (error) {
      console.error('🛑 后端会话中断失败:', error)
    }
  }
  
  setIsLoading(false)
}

const formatToolResult = (result) => {
  if (!result) return t('chat.noResult')
  if (typeof result === 'string') return result
  return JSON.stringify(result, null, 2)
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesEndRef.value) {
      messagesEndRef.value.scrollIntoView({ behavior: 'smooth' })
    }
  })
}

const triggerAutoSave = () => {
  if (currentSessionId.value && messages.value && messages.value.length > 0) {
    const conversation = {
      id: currentSessionId.value,
      title: (messages.value && messages.value[0] && typeof messages.value[0]?.content === 'string' ? messages.value[0].content.substring(0, 50) : '新对话') || '新对话',
      messages: messages.value || [],
      timestamp: Date.now(),
      agentId: selectedAgent.value?.id
    }
    
    emit('update-conversation', conversation)
    saveSession(currentSessionId.value, {
      messages: messages.value || [],
      agentId: selectedAgent.value?.id,
      config: config
    })
  }
}

const handleSendMessage = async (messageText) => {
  if (isLoading.value || !messageText.trim() || !selectedAgent.value) {
    return
  }

  try {
    setIsLoading(true)
    
    let sessionId = currentSessionId.value
    if (!sessionId) {
      sessionId = createSession()
      console.log('🆕 创建新会话:', sessionId)
    }

    addUserMessage(messageText)
    scrollToBottom()

    console.log('📡 准备调用sendMessage API，参数:', {
      messageLength: messageText.length,
      sessionId,
      agentName: selectedAgent.value.name,
      configKeys: Object.keys(config || {})
    })

    await sendMessage(
      messageText,
      sessionId,
      config,
      selectedAgent.value,
      (data) => {
        console.log('🧩 ChatPage收到分块消息回调:', data.type, data.message_id)
        handleChunkMessage(data)
      },
      (data) => {
        console.log('📨 ChatPage收到普通消息回调:', data.type || data.message_type, data.message_id)
        handleMessage(data)
      }
    )
  } catch (error) {
    console.error('❌ ChatPage发送消息异常:', error)
    addErrorMessage(error)
    setIsLoading(false)
  }
}

const startNewConversation = () => {
  if (currentSessionId.value && messages.value && messages.value.length > 0) {
    triggerAutoSave()
  }
  
  clearMessages()
  const newSessionId = createSession()
  console.log('🆕 开始新对话:', newSessionId)
  
  return newSessionId
}

// ===== Watchers =====
watch(() => props.selectedConversation, (conversation) => {
  if (conversation) {
    console.log('📖 加载选中的对话:', conversation.id)
    setMessages(conversation.messages || [])
    loadSession(conversation.id)
    
    if (conversation.agentId) {
    const agent = agents.value.find(a => a.id === conversation.agentId)
    if (agent) {
      selectAgent(agent)
    }
  }
    
    emit('clear-selected-conversation')
    scrollToBottom()
  }
}, { immediate: true })

watch(messages, () => {
  scrollToBottom()
  if (messages.value && messages.value.length > 0) {
    triggerAutoSave()
  }
}, { deep: true })

watch(isLoading, (newValue, oldValue) => {
  if (oldValue && !newValue) {
    triggerAutoSave()
  }
})

// 从API获取数据
const agents = ref([])
const agentsLoading = ref(false)

// 加载agents
const loadAgents = async () => {
  try {
    agentsLoading.value = true
    const agentList = await agentAPI.getAgents()
    agents.value = agentList || []
  } catch (error) {
    console.error('加载agents失败:', error)
    agents.value = []
  } finally {
    agentsLoading.value = false
  }
}

// 获取默认agent
const getDefaultAgent = () => {
  // 优先返回ID为'default'的agent
  const defaultAgent = agents.value.find(agent => agent.id === 'default')
  if (defaultAgent) {
    return defaultAgent
  }
  
  // 如果没有找到默认agent，返回第一个agent
  return agents.value.length > 0 ? agents.value[0] : null
}

// ===== Lifecycle =====
onMounted(async () => {
  await createSession()
  
  await loadAgents()
  
  if (agents.value && agents.value.length > 0 && !selectedAgent.value) {
    const defaultAgent = getDefaultAgent()
    if (defaultAgent) {
      selectAgent(defaultAgent)
    } else {
      selectAgent(agents.value[0])
    }
  }
})

// ===== Expose =====
defineExpose({
  startNewConversation
})
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.chat-title h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.25rem;
  font-weight: 600;
}

.agent-name {
  color: var(--text-secondary);
  font-size: 0.875rem;
  margin-left: 0.5rem;
}

.chat-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.agent-select {
  min-width: 150px;
}

:deep(.el-select) {
  width: 100%;
}

:deep(.el-select .el-input) {
  border-radius: 6px;
}

:deep(.el-select-dropdown) {
  z-index: 9999 !important;
}

:deep(.el-popper) {
  z-index: 9999 !important;
}

.chat-container {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.chat-container.split-view .chat-messages {
  flex: 1;
}

.chat-messages {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 2rem;
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
  margin: 0;
  font-size: 0.875rem;
}

.messages-list {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.loading-indicator {
  display: flex;
  justify-content: center;
  padding: 1rem;
}

.loading-dots {
  display: flex;
  gap: 0.25rem;
}

.loading-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary-color);
  animation: loading-bounce 1.4s ease-in-out infinite both;
}

.loading-dots span:nth-child(1) { animation-delay: -0.32s; }
.loading-dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes loading-bounce {
  0%, 80%, 100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
}

.tool-details-panel {
  width: 400px;
  border-left: 1px solid var(--border-color);
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
}

.tool-details-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
}

.tool-details-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.tool-details-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.tool-section {
  margin-bottom: 1.5rem;
}

.tool-section h4 {
  margin: 0 0 0.5rem 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.tool-code {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 0.75rem;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  font-size: 0.75rem;
  line-height: 1.4;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>