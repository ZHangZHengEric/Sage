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
        <el-select v-model="selectedAgentId" class="agent-select" @change="handleAgentChange">
          <el-option v-for="agent in (agents || [])" :key="agent.id" :label="agent.name" :value="agent.id" />
        </el-select>
        <el-button type="text" @click="showSettings = !showSettings" :title="t('chat.settings')">
          <Settings :size="16" />
        </el-button>

      </div>
    </div>
    <div
      :class="['chat-container', { 'split-view': showToolDetails || showTaskStatus || showWorkspace || showSettings }]">
      <div class="chat-messages">
        <div v-if="!messages || messages.length === 0" class="empty-state">
          <Bot :size="48" class="empty-icon" />
          <h3>{{ t('chat.emptyTitle') }}</h3>
          <p>{{ t('chat.emptyDesc') }}</p>
        </div>
        <div v-else class="messages-list">
          <MessageRenderer v-for="(message, index) in (messages || [])" :key="message.id || index" :message="message"
            :messages="messages || []" :message-index="index" @download-file="downloadFile"
            @toolClick="handleToolClick" />
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
          <el-button type="text" @click="showToolDetails = false">
            ×
          </el-button>
        </div>
        <div class="tool-details-content">
          <div class="tool-section">
            <h4>{{ t('chat.toolName') }}</h4>
            <p>{{ selectedToolExecution.function.name }}</p>
          </div>
          <div class="tool-section">
            <h4>{{ t('chat.toolParams') }}</h4>
            <pre class="tool-code">{{ JSON.stringify(selectedToolExecution.function.arguments, null, 2) }}</pre>
          </div>
          <div class="tool-section">
            <h4>{{ t('chat.toolResult') }}</h4>
            <pre class="tool-code">{{ formatToolResult(toolResult) }}</pre>
          </div>
        </div>
      </div>

      <TaskStatusPanel v-if="showTaskStatus" :task-status="taskStatus" :expanded-tasks="expandedTasks"
        @toggle-task-expanded="toggleTaskExpanded" @close="showTaskStatus = false" />

      <WorkspacePanel v-if="showWorkspace" :workspace-files="workspaceFiles" :workspace-path="workspacePath"
        @download-file="downloadFile" @close="showWorkspace = false" />

      <ConfigPanel v-if="showSettings" :agents="agents" :selected-agent="selectedAgent" :config="config"
        @config-change="updateConfig" @close="showSettings = false" />
    </div>

    <MessageInput :is-loading="isLoading" @send-message="handleSendMessage" @stop-generation="interruptSession" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Bot, Settings, List, Folder } from 'lucide-vue-next'

import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ConfigPanel from '@/components/chat/ConfigPanel.vue'
import TaskStatusPanel from '@/components/chat/TaskStatusPanel.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'

import { useMessages } from '@/composables/useMessages'
import { useSession } from '@/composables/useSession'
import { useTaskManager } from '@/composables/useTaskManager'
import { useLanguage } from '@/utils/language.js'
import { getAgents } from '@/api'

// Props
const props = defineProps({
  selectedConversation: {
    type: Object,
    default: null
  }
})

const { t } = useLanguage()

// 状态管理
const messagesEndRef = ref(null)
const showSettings = ref(false)
const showToolDetails = ref(false)
const showTaskStatus = ref(false)
const showWorkspace = ref(false)
const selectedToolExecution = ref(null)
const toolResult = ref(null)

const agents = ref([])
const expandedTasks = ref(new Set())

// 使用 composables
const {
  messages,
  isLoading,
  addUserMessage,
  updateLastMessage,
  clearMessages,
  handleMessage,
  handleChunkMessage
} = useMessages()

const {
  currentSessionId,
  selectedAgent,
  config,
  createSession,
  updateConfig: updateSessionConfig,
  selectAgent
} = useSession(agents)


const {
  taskStatus,
  workspaceFiles,
  workspacePath,
  downloadFile: downloadWorkspaceFile
} = useTaskManager()

// 计算属性
const selectedAgentId = computed(() => selectedAgent.value?.id)

// 方法
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesEndRef.value) {
      messagesEndRef.value.scrollIntoView({ behavior: 'smooth' })
    }
  })
}

const loadAgents = async () => {
  try {
    const response = await getAgents()
    agents.value = response || []
  } catch (error) {
    console.error('Failed to load agents:', error)
    ElMessage.error(t('chat.loadAgentsError'))
  }
}

const handleAgentChange = async (agentId) => {
  if (agentId !== selectedAgentId.value) {
    const agent = agents.value.find(a => a.id === agentId)
    if (agent) {
      selectAgent(agent)
      await createSession(agentId)
      clearMessages()
    }
  }
}


// 加载conversation数据
const loadConversationData = async (conversation) => {
  try {
    // 清除当前消息
    clearMessages()

    // 根据conversation中的agent_id选择对应的agent
    if (conversation.agent_id && agents.value.length > 0) {
      const agent = agents.value.find(a => a.id === conversation.agent_id)
      if (agent) {
        selectAgent(agent)
      } else {
        // 如果找不到对应的agent，使用第一个agent
        selectAgent(agents.value[0])
      }
    }

    // 加载消息
    if (conversation.messages && conversation.messages.length > 0) {
      messages.value = conversation.messages
    }
    currentSessionId.value = conversation.session_id || null
    // 滚动到底部
    nextTick(() => {
      scrollToBottom()
    })


  } catch (error) {
    console.error('Failed to load conversation data:', error)
    ElMessage.error(t('chat.loadConversationError'))
  }
}

const updateConfig = (newConfig) => {
  updateSessionConfig(newConfig)
}

const handleSendMessage = async (content) => {
  if (!content.trim() || isLoading.value || !selectedAgent.value) return;

  console.log('🚀 开始发送消息:', content.substring(0, 100) + (content.length > 100 ? '...' : ''));

  // 如果没有会话ID，创建新的会话ID
  let sessionId = currentSessionId.value;
  if (!sessionId) {
    sessionId = await createSession(selectedAgent.value.id);
    console.log('🆕 创建新会话ID:', sessionId);
  }

  // 添加用户消息
  addUserMessage(content);

  try {

    console.log('📡 准备调用sendMessage API，参数:', {
      messageLength: content.length,
      sessionId,
      agentName: selectedAgent.value.name,
      configKeys: Object.keys(config.value || {})
    });

    scrollToBottom()
    // 使用新的发送消息API
    await sendMessageApi({
      message: content,
      sessionId: sessionId,
      selectedAgent: selectedAgent.value,
      config: config.value,
      abortControllerRef: null, // Vue版本可能不需要这个
      onMessage: (data) => {
        handleMessage(data);
      },
      onChunkMessage: (data) => {
        handleChunkMessage(data);
      },

      onComplete: async () => {
        scrollToBottom()
      },
      onError: (error) => {
        console.error('❌ Chat.vue消息发送错误:', error);
        ElMessage.error(t('chat.sendError'))
      }
    })
  } catch (error) {
    console.error('❌ Chat.vue发送消息异常:', error);
    ElMessage.error(t('chat.sendError'))
  }
}


const handleToolClick = (toolExecution, result) => {

  selectedToolExecution.value = toolExecution
  toolResult.value = result
  showToolDetails.value = true
}


const toggleTaskExpanded = (taskId) => {
  if (expandedTasks.value.has(taskId)) {
    expandedTasks.value.delete(taskId)
  } else {
    expandedTasks.value.add(taskId)
  }
}

const formatToolResult = (result) => {
  if (typeof result === 'string') {
    return result
  }
  return JSON.stringify(result, null, 2)
}

const downloadFile = async (filename) => {
  try {
    if (currentSessionId.value) {
      await downloadWorkspaceFile(currentSessionId.value, filename)
    }
  } catch (error) {
    console.error('Failed to download file:', error)
    ElMessage.error(t('chat.downloadError'))
  }
}

 // 发送消息到后端
  const sendMessageApi = async ({
    message,
    sessionId,
    selectedAgent,
    config,
    abortControllerRef,
    onMessage,
    onChunkMessage,
    onError,
    onComplete
  }) => {
    try {
      // 创建新的 AbortController
      if (abortControllerRef) {
        abortControllerRef.value = new AbortController();
      }
      
      const requestBody = {
        messages: [{
          role: 'user',
          content: message
        }],
        user_id: "default_user",
        session_id: sessionId,
        deep_thinking: config.deepThinking,
        multi_agent: config.multiAgent,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount,
        agent_id: selectedAgent?.id || "default_agent",
        agent_name: selectedAgent?.name || "Sage Assistant",
        system_context: selectedAgent?.systemContext || {},
        available_workflows: selectedAgent?.availableWorkflows || {},
        llm_model_config: selectedAgent?.llmConfig || {
          model: '',
          maxTokens: 4096,
          temperature: 0.7
        },
        system_prefix: selectedAgent?.systemPrefix || 'You are a helpful AI assistant.',
        available_tools: selectedAgent?.availableTools || []
      };
      
      // 在浏览器控制台显示聊天时的配置参数
      console.log('📥 传入的config对象:', config);
      console.log('🚀 聊天请求配置参数:', {
        deep_thinking: config.deepThinking,
        multi_agent: config.multiAgent,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount
      });  
      const response = await fetch('/api/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
        signal: abortControllerRef?.value?.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let messageCount = 0;

      console.log('🌊 开始读取WebSocket流数据');

      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          console.log('📡 WebSocket流读取完成，总共处理', messageCount, '条消息');
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // 保留不完整的行

        for (const line of lines) {
          if (line.trim() === '') continue;
          
          messageCount++;
          
          try {
            const messageData = JSON.parse(line);
            
            // 处理分块消息
            if (messageData.type === 'chunk_start' || 
                messageData.type === 'json_chunk' || 
                messageData.type === 'chunk_end') {
              console.log('🧩 分块消息:', messageData.type, messageData);
              if (onChunkMessage) {
                onChunkMessage(messageData);
              }
         
            } else {
              // 处理普通消息
              if (onMessage) {
                onMessage(messageData);
              }
          
            }
          } catch (parseError) {
            console.error('❌ JSON解析失败:', parseError);
            console.error('📄 原始行内容:', line);
          }
        }
      }
      
      onComplete();
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('Request was aborted');
      } else {
        console.error('Error sending message:', error);
        onError(error);
      }
    }
  };

  // 中断会话
  const interruptSession = async (sessionId) => {
    if (!sessionId) return;
    
    try {
      await fetch(`/api/sessions/${sessionId}/interrupt`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: '用户请求中断'
        })
      });
      console.log('Session interrupted successfully');
    } catch (error) {
      console.error('Error interrupting session:', error);
    }
  };

// 生命周期
onMounted(async () => {
  await loadAgents()

  // 检查是否有传递的conversation数据
  if (props.selectedConversation) {
    await loadConversationData(props.selectedConversation)
  } else if (agents.value.length > 0) {
    // 如果没有选中的agent，默认选择第一个
    if (!selectedAgent.value) {
      selectAgent(agents.value[0])
    }
    // 如果没有当前会话，创建新会话
    if (!currentSessionId.value) {
      await createSession()
    }
  }
})


// 监听selectedConversation变化
watch(() => props.selectedConversation, async (newConversation) => {
  if (newConversation && agents.value.length > 0) {
    await loadConversationData(newConversation)
  }
}, { immediate: false })

// 监听消息变化，自动滚动到底部
watch(messages, () => {
  scrollToBottom()
}, { deep: true })


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

.chat-container {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.chat-container.split-view .chat-messages {
  flex: 1;
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

.loading-dots span:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes loading-bounce {

  0%,
  80%,
  100% {
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