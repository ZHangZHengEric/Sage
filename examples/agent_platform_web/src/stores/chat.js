import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatAPI, taskAPI } from '../api/index.js'

export const useChatStore = defineStore('chat', () => {
  // 状态
  const conversations = ref([])
  const currentConversation = ref(null)
  const messages = ref([])
  const messageChunks = ref({})
  const isLoading = ref(false)
  const inputMessage = ref('')
  const currentSessionId = ref(null)
  const taskStatus = ref([])
  const workspaceFiles = ref([])
  const workspacePath = ref('')
  const expandedTasks = ref({})
  const lastMessageId = ref(null)
  
  // 计算属性
  const hasMessages = computed(() => messages.value.length > 0)
  const messageCount = computed(() => messages.value.length)
  const hasConversations = computed(() => conversations.value.length > 0)
  const conversationCount = computed(() => conversations.value.length)
  const hasActiveTasks = computed(() => taskStatus.value.length > 0)
  const hasWorkspaceFiles = computed(() => workspaceFiles.value.length > 0)
  
  // 方法
  const setMessages = (newMessages) => {
    messages.value = newMessages
  }
  
  const addMessage = (message) => {
    messages.value.push(message)
  }
  
  const updateMessage = (messageId, updates) => {
    const index = messages.value.findIndex(msg => msg.id === messageId)
    if (index !== -1) {
      messages.value[index] = { ...messages.value[index], ...updates }
    }
  }
  
  const clearMessages = () => {
    messages.value = []
    messageChunks.value = {}
  }
  
  const setMessageChunks = (chunks) => {
    messageChunks.value = chunks
  }
  
  const updateMessageChunk = (messageId, chunk) => {
    if (!messageChunks.value[messageId]) {
      messageChunks.value[messageId] = []
    }
    messageChunks.value[messageId].push(chunk)
  }
  
  const clearMessageChunks = (messageId) => {
    if (messageId) {
      delete messageChunks.value[messageId]
    } else {
      messageChunks.value = {}
    }
  }
  
  const setIsLoading = (loading) => {
    isLoading.value = loading
  }
  
  const setInputMessage = (message) => {
    inputMessage.value = message
  }
  
  const setCurrentSessionId = (sessionId) => {
    currentSessionId.value = sessionId
  }
  
  const setConversations = (convs) => {
    conversations.value = convs
  }
  
  const addConversation = (conversation) => {
    conversations.value.unshift(conversation)
  }
  
  const updateConversation = (conversationId, updates) => {
    const index = conversations.value.findIndex(conv => conv.id === conversationId)
    if (index !== -1) {
      conversations.value[index] = { ...conversations.value[index], ...updates }
    }
  }
  
  const deleteConversation = (conversationId) => {
    const index = conversations.value.findIndex(conv => conv.id === conversationId)
    if (index !== -1) {
      conversations.value.splice(index, 1)
    }
  }
  
  const setCurrentConversation = (conversation) => {
    currentConversation.value = conversation
  }
  
  const setTaskStatus = (tasks) => {
    taskStatus.value = tasks
  }
  
  const setWorkspaceFiles = (files) => {
    workspaceFiles.value = files
  }
  
  const setWorkspacePath = (path) => {
    workspacePath.value = path
  }
  
  const setExpandedTasks = (expanded) => {
    expandedTasks.value = expanded
  }
  
  const toggleTaskExpanded = (taskId) => {
    expandedTasks.value[taskId] = !expandedTasks.value[taskId]
  }
  
  const setLastMessageId = (messageId) => {
    lastMessageId.value = messageId
  }
  
  // 创建新会话
  const createSession = async () => {
    try {
      const data = await chatAPI.createSession()
      setCurrentSessionId(data.session_id)
      return data.session_id
    } catch (err) {
      console.error('Failed to create session:', err)
      throw err
    }
  }
  
  // 清除会话
  const clearSession = () => {
    setCurrentSessionId(null)
    clearMessages()
    setTaskStatus([])
    setWorkspaceFiles([])
    setWorkspacePath('')
    setExpandedTasks({})
    setLastMessageId(null)
  }
  
  // 从localStorage加载对话历史
  const loadConversationsFromStorage = () => {
    try {
      const saved = localStorage.getItem('conversations')
      if (saved) {
        const data = JSON.parse(saved)
        setConversations(data)
      } else {
        // 设置默认对话数据
        const defaultConversations = []
        setConversations(defaultConversations)
        saveConversationsToStorage()
      }
    } catch (err) {
      console.error('Failed to load conversations from storage:', err)
      setConversations([])
    }
  }

  // 保存对话到localStorage
  const saveConversationsToStorage = () => {
    try {
      localStorage.setItem('conversations', JSON.stringify(conversations.value))
    } catch (err) {
      console.error('Failed to save conversations to storage:', err)
    }
  }

  // 加载对话历史
  const loadConversations = async () => {
    try {
      // 优先从localStorage加载
      loadConversationsFromStorage()
    } catch (err) {
      console.error('Failed to load conversations:', err)
      throw err
    }
  }

  // 分页加载对话列表
  const loadConversationsPaginated = async (params = {}) => {
    try {
      const response = await chatAPI.getConversationsPaginated(params)
      return response
    } catch (err) {
      console.error('Failed to load conversations paginated:', err)
      throw err
    }
  }
  
  // 加载特定对话的消息
  const loadConversationMessages = async (conversationId) => {
    try {
      const data = await chatAPI.getConversationMessages(conversationId)
      setMessages(data.messages || [])
      setCurrentSessionId(data.session_id)
    } catch (err) {
      console.error('Failed to load conversation messages:', err)
      throw err
    }
  }
  
  // 保存对话
  const saveConversation = async (title, agentId) => {
    try {
      const conversation = await chatAPI.saveConversation({
        title,
        agent_id: agentId,
        session_id: currentSessionId.value,
        messages: messages.value
      })
      addConversation(conversation)
      return conversation
    } catch (err) {
      console.error('Failed to save conversation:', err)
      throw err
    }
  }
  
  // 删除对话
  const removeConversation = async (conversationId) => {
    try {
      await chatAPI.deleteConversation(conversationId)
      deleteConversation(conversationId)
    } catch (err) {
      console.error('Failed to delete conversation:', err)
      throw err
    }
  }
  
  // 获取任务状态
  const fetchTaskStatus = async (sessionId) => {
    if (!sessionId) return
    
    try {
      const data = await taskAPI.getTaskStatus(sessionId)
      setTaskStatus(data.tasks || [])
    } catch (err) {
      console.error('Failed to fetch task status:', err)
    }
  }
  
  // 获取工作空间文件
  const fetchWorkspaceFiles = async (sessionId) => {
    if (!sessionId) return
    
    try {
      const data = await taskAPI.getWorkspaceFiles(sessionId)
      setWorkspaceFiles(data.files || [])
      setWorkspacePath(data.workspace_path || '')
    } catch (err) {
      console.error('Failed to fetch workspace files:', err)
    }
  }
  
  // 下载文件
  const downloadFile = async (filePath) => {
    try {
      const blob = await taskAPI.downloadFile(filePath, workspacePath.value)
      
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filePath.split('/').pop()
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      console.error('Failed to download file:', err)
      throw err
    }
  }
  
  // 初始化
  const initialize = async () => {
    await loadConversations()
  }
  
  return {
    // 状态
    conversations,
    currentConversation,
    messages,
    messageChunks,
    isLoading,
    inputMessage,
    currentSessionId,
    taskStatus,
    workspaceFiles,
    workspacePath,
    expandedTasks,
    lastMessageId,
    
    // 计算属性
    hasMessages,
    messageCount,
    hasConversations,
    conversationCount,
    hasActiveTasks,
    hasWorkspaceFiles,
    
    // 方法
    setMessages,
    addMessage,
    updateMessage,
    clearMessages,
    setMessageChunks,
    updateMessageChunk,
    clearMessageChunks,
    setIsLoading,
    setInputMessage,
    setCurrentSessionId,
    setConversations,
    addConversation,
    updateConversation,
    deleteConversation,
    setCurrentConversation,
    setTaskStatus,
    setWorkspaceFiles,
    setWorkspacePath,
    setExpandedTasks,
    toggleTaskExpanded,
    setLastMessageId,
    createSession,
    clearSession,
    loadConversations,
    loadConversationsPaginated,
    loadConversationMessages,
    saveConversation,
    removeConversation,
    fetchTaskStatus,
    fetchWorkspaceFiles,
    downloadFile,
    initialize
  }
})