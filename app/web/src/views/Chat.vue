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
                <Button variant="ghost" size="icon" class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="handleShare">
                  <Share2 class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('chat.share') }}</p>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="hidden sm:inline-flex h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/80" @click="showTrace = !showTrace">
                  <Activity class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ t('chat.traceWorkflow') }}</p>
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
          <div v-if="!messages || messages.length === 0" class="flex flex-col items-center justify-center text-center p-8 h-full text-muted-foreground animate-in fade-in zoom-in duration-500">
            <div class="w-16 h-16 rounded-2xl bg-muted/50 flex items-center justify-center mb-6 shadow-sm">
               <Bot :size="32" class="opacity-80 text-primary" />
            </div>
            <h3 class="mb-3 text-xl font-semibold text-foreground">{{ t('chat.emptyTitle') }}</h3>
            <p class="mb-8 text-sm max-w-md mx-auto leading-relaxed text-muted-foreground/80">{{ t('chat.emptyDesc') }}</p>
          </div>
          <div v-else class="pb-8 max-w-4xl mx-auto w-full">
            <MessageRenderer 
              v-for="(message, index) in (messages || [])" 
              :key="message.id || index" 
              :message="message"
              :messages="messages || []" 
              :message-index="index" 
              :is-loading="isLoading && index === (messages || []).length - 1"
              @download-file="downloadFile"
              @toolClick="handleToolClick" 
              @sendMessage="handleSendMessage" 
            />
            
            <!-- Global loading indicator when no messages or waiting for first chunk of response -->
            <div v-if="isLoading && (!messages || messages.length === 0 || messages[messages.length - 1].role === 'user')" class="flex justify-start py-6 px-4 animate-in fade-in duration-300">
               <LoadingBubble />
            </div>
          </div>
          <div ref="messagesEndRef" />
        </div>
        
        <div class="flex-none p-4  bg-background" v-if="selectedAgent">
            <MessageInput :is-loading="isLoading" @send-message="handleSendMessage" @stop-generation="stopGeneration" />
        </div>
      </div>

      <WorkspacePanel v-if="showWorkspace" :workspace-files="workspaceFiles"
        @download-file="downloadFile" @close="showWorkspace = false" />

      <WorkflowPanel v-if="showTrace && currentSessionId" :session-id="currentSessionId" @close="showTrace = false" />

      <ConfigPanel v-if="showSettings" :agents="agents" :selected-agent="selectedAgent" :config="config"
        @config-change="updateConfig" @close="showSettings = false" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { toast } from 'vue-sonner'
import { Bot, Settings, Activity, Share2, FolderOpen } from 'lucide-vue-next'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MessageRenderer from '@/components/chat/MessageRenderer.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ConfigPanel from '@/components/chat/ConfigPanel.vue'
import WorkspacePanel from '@/components/chat/WorkspacePanel.vue'
import WorkflowPanel from '@/components/chat/WorkflowPanel.vue'
import LoadingBubble from '@/components/chat/LoadingBubble.vue'

// UI Components
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import { useLanguage } from '@/utils/i18n.js'
import { agentAPI} from '../api/agent.js'
import { chatAPI } from '../api/chat.js'
import { taskAPI } from '../api/task.js'
import { isLoggedIn } from '@/utils/auth.js'

// Props
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
const route = useRoute()

// 状态管理
const messagesEndRef = ref(null)
const messagesListRef = ref(null)
const showSettings = ref(false)
const showToolDetails = ref(false)
const showTaskStatus = ref(false)
const showWorkspace = ref(false)
const showTrace = ref(false)
const selectedToolExecution = ref(null)
const toolResult = ref(null)

// 滚动相关状态
const isUserScrolling = ref(false)
const isAutoScrolling = ref(false)
const shouldAutoScroll = ref(true)
const scrollTimeout = ref(null)

const agents = ref([])
const expandedTasks = ref(new Set())
const messages = ref([]);
const messageChunks = ref(new Map());
const isLoading = ref(false);
const abortControllerRef = ref(null);
const currentSessionId = ref(null);
const selectedAgent = ref(null);
const config = ref({
    deepThinking: true,
    agentMode: 'simple',
    moreSuggest: false,
    maxLoopCount: 10
});
const userConfigOverrides = ref({});
const taskStatus = ref(null);
const workspaceFiles = ref([]);
const lastMessageId = ref(null);

  // 获取任务状态
const fetchTaskStatus = async (sessionId) => {
    if (!sessionId) return;
    try {
      const data = await taskAPI.getTaskStatus(sessionId);
      const tasksObj = data.tasks_status?.tasks || {};
      // 将任务对象转换为数组
      const tasks = Object.values(tasksObj);
      tasks.forEach((task, index) => {
        if (task.execution_summary) {
        }
      });
      taskStatus.value = tasks;
    } catch (error) {
      console.error('获取任务状态出错:', error);
    }
  };

  // 获取工作空间文件
  const fetchWorkspaceFiles = async (sessionId) => {
    if (!sessionId) return;
    try {
      const data = await taskAPI.getWorkspaceFiles(sessionId);
      workspaceFiles.value = data.files || [];
    } catch (error) {
      console.error('获取工作空间文件出错:', error);
    }
  };

  const handleWorkspacePanel = () => {
    showWorkspace.value = !showWorkspace.value;
    if (showWorkspace.value) {
      updateTaskAndWorkspace(currentSessionId.value);
    }
  }

  // 下载文件
  const downloadWorkspaceFile = async (sessionId, itemOrPath) => {
    if (!sessionId || !itemOrPath) return;
    
    // 兼容处理：itemOrPath可能是字符串路径，也可能是文件对象
    const filePath = typeof itemOrPath === 'string' ? itemOrPath : itemOrPath.path;
    const isDirectory = typeof itemOrPath === 'object' ? itemOrPath.is_directory : false;
    
    if (!filePath) return;

    try {
      const blob = await taskAPI.downloadFile(sessionId, filePath);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      
      let filename = filePath.split('/').pop();
      if (isDirectory && !filename.endsWith('.zip')) {
        filename += '.zip';
      }
      
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error('下载文件出错:', error);
      toast.error(t('chat.downloadError') || `Download failed: ${error.message}`);
    }
  };

  // 切换任务展开状态
const toggleTaskExpanded = (taskId) => {
    const newSet = new Set(expandedTasks.value);
    if (newSet.has(taskId)) {
      newSet.delete(taskId);
    } else {
      newSet.add(taskId);
    }
    expandedTasks.value = newSet;
  };

  // 更新任务和工作空间数据
  const updateTaskAndWorkspace = (sessionId, reason = 'unknown') => {
    if (sessionId) {
      fetchWorkspaceFiles(sessionId);
    }
  };

  // 清空任务和工作空间数据
  const clearTaskAndWorkspace = () => {
    taskStatus.value = null;
    workspaceFiles.value = [];
    expandedTasks.value = new Set();
    lastMessageId.value = null;
  };


  // 创建新会话
const createSession = () => {
    const sessionId = `session_${Date.now()}`;
    currentSessionId.value = sessionId;
    return sessionId;
  };

  // 处理会话加载
  const handleSessionLoad = async (sessionId) => {
    if (!sessionId) return;
    
    currentSessionId.value = sessionId;
    isLoading.value = true;
    
    try {
      // 获取会话消息
      const res = await chatAPI.getConversationMessages(sessionId);
      if (res && res.messages) {
        // 加载消息
        messages.value = res.messages;
        if (res.conversation_info) {
          // 如果有 conversation_info，可以在这里恢复其他状态
          // 比如选中的 agent
          if (res.conversation_info.agent_id) {
            const agent = agents.value.find(a => a.id === res.conversation_info.agent_id);
            if (agent) {
              selectAgent(agent);
            }
          }
        }
      }
      
    
    } catch (e) {
      console.error('加载会话失败:', e);
      toast.error(t('chat.loadConversationError') || 'Failed to load conversation');
    } finally {
      isLoading.value = false;
    }
  };

  // 更新配置
const updateConfig = (newConfig) => {
    console.log('🔧 updateConfig被调用，newConfig:', newConfig);
    console.log('🔧 当前config状态(prev):', config.value);
    const updatedConfig = { ...config.value, ...newConfig };
    console.log('🔧 更新后的config:', updatedConfig);
    config.value = updatedConfig;
    
    // 记录用户手动修改的配置项，这些配置项将优先于agent配置
    const updatedOverrides = { ...userConfigOverrides.value, ...newConfig };
    console.log('🔧 更新后的userConfigOverrides:', updatedOverrides);
    userConfigOverrides.value = updatedOverrides;
  };

  // 设置选中的智能体
  const selectAgent = (agent, forceConfigUpdate = false) => {
    const isAgentChange = !selectedAgent.value || selectedAgent.value.id !== agent?.id;
    selectedAgent.value = agent;
    if (agent && (isAgentChange || forceConfigUpdate)) {
      // 只有在agent真正改变或强制更新时才重新设置配置
      // 配置设置的优先级高于agent配置：用户手动修改的配置项优先，其次是agent配置，最后是默认值
      config.value = {
        deepThinking: userConfigOverrides.value.deepThinking !== undefined ? userConfigOverrides.value.deepThinking : agent.deepThinking,
        agentMode: userConfigOverrides.value.agentMode !== undefined ? userConfigOverrides.value.agentMode : (agent.agentMode || 'simple'),
        moreSuggest: userConfigOverrides.value.moreSuggest !== undefined ? userConfigOverrides.value.moreSuggest : (agent.moreSuggest ?? false),
        maxLoopCount: userConfigOverrides.value.maxLoopCount !== undefined ? userConfigOverrides.value.maxLoopCount : (agent.maxLoopCount ?? 10)
      };
      localStorage.setItem('selectedAgentId', agent.id);
    }
  };

  // 监听重置 Token
  watch(() => props.chatResetToken, (newVal) => {
    if (newVal) {
      console.log('🔄 检测到重置信号，重置聊天状态');
      resetChat();
      if (isLoading.value) {
        stopGeneration();
      }
    }
  });

  // 从localStorage恢复选中的智能体
  const restoreSelectedAgent = (agentsList) => {
    console.log('🔍 尝试恢复选中的智能体，agents数量:', agentsList?.length || 0, '当前选中的agent:', selectedAgent.value?.id || 'none');
    
    if (!agentsList || agentsList.length === 0) {
      console.warn('⚠️ agents列表为空，无法恢复选中的智能体');
      return;
    }

    // 如果已经有选中的智能体，检查是否在当前列表中
    if (selectedAgent.value) {
      const currentAgentExists = agentsList.find(agent => agent.id === selectedAgent.value.id);
      if (currentAgentExists) {
        console.log('✅ 当前选中的智能体仍然存在，无需恢复');
        return;
      } else {
        console.log('⚠️ 当前选中的智能体不在列表中，需要重新选择');
      }
    }

    const savedAgentId = localStorage.getItem('selectedAgentId');
    console.log('🔍 从localStorage获取保存的智能体ID:', savedAgentId);
    
    if (savedAgentId) {
      const savedAgent = agentsList.find(agent => agent.id === savedAgentId);
      if (savedAgent) {
        console.log('✅ 找到保存的智能体，正在恢复:', savedAgent.name);
        selectAgent(savedAgent);
        return;
      } else {
        console.warn('⚠️ 保存的智能体不存在，选择第一个智能体');
      }
    } else {
      console.log('ℹ️ 没有保存的智能体ID，选择第一个智能体');
    }
    
    // 选择第一个智能体作为默认选择
    if (agentsList[0]) {
      console.log('🎯 选择默认智能体:', agentsList[0].name);
      selectAgent(agentsList[0]);
    }
  };



// 处理分块消息合并
const handleChunkMessage = (messageData) => {
  console.log('🧩 收到分块消息:', messageData.type, messageData);

  const newChunks = new Map(messageChunks.value);
  // 使用message_id作为分组标识符，而不是chunk_id
  const messageId = messageData.message_id;

  if (messageData.type === 'chunk_start') {
    console.log('🚀 开始接收分块消息:', messageId, '总块数:', messageData.total_chunks);
    // 初始化chunk数据收集
    newChunks.set(messageId, {
      chunks: [],
      total_chunks: messageData.total_chunks,
      original_type: messageData.original_type,
      message_id: messageData.message_id,
      received_chunks: 0
    });
  } else if (messageData.type === 'json_chunk') {
    console.log('📦 收到数据块:', messageData.chunk_index + 1, '/', messageData.total_chunks);
    // 收集json_chunk数据
    const existing = newChunks.get(messageId);
    if (existing) {
      // 检查是否已经收到过这个chunk_index，避免重复
      const isDuplicate = existing.chunks.some(chunk => chunk.chunk_index === messageData.chunk_index);
      if (!isDuplicate) {
        existing.chunks.push(messageData);
        existing.received_chunks = existing.chunks.length;
        console.log('📊 已收到块数:', existing.received_chunks, '/', existing.total_chunks);
      } else {
        console.warn('⚠️ 收到重复的chunk_index:', messageData.chunk_index, '忽略');
      }
    } else {
      console.warn('⚠️ 收到chunk但没有找到对应的chunk_start:', messageId);
      // 创建新的chunk收集器（容错处理）
      newChunks.set(messageId, {
        chunks: [messageData],
        total_chunks: messageData.total_chunks,
        message_id: messageId,
        received_chunks: 1
      });
    }
  } else if (messageData.type === 'chunk_end') {
    console.log('🏁 分块传输结束:', messageId);
    // chunk_end时重组完整消息
    const chunkData = newChunks.get(messageId);
    if (chunkData) {
      console.log('🔧 重组消息: 收到', chunkData.received_chunks, '块，期望', chunkData.total_chunks, '块');

      try {
        // 按chunk_index排序分块数据
        const sortedChunks = chunkData.chunks.sort((a, b) => a.chunk_index - b.chunk_index);

        // 拼接所有分块数据
        const completeData = sortedChunks.map(chunk => chunk.chunk_data).join('');
        console.log('📄 完整数据长度:', completeData.length, '字符');

        // 解析完整的JSON数据
        const fullData = JSON.parse(completeData);
        console.log('✅ 成功解析分块JSON数据:', fullData.type || fullData.message_type);

        // 使用handleMessage处理重组后的完整消息
        const completeMessage = {
          ...fullData,
          timestamp: messageData.timestamp || Date.now()
        };

        // 直接调用handleMessage处理完整消息
        setTimeout(() => {
          handleMessage(completeMessage);
        }, 0);

        // 清理chunk数据
        newChunks.delete(messageId);
        console.log('🧹 清理分块数据完成');
      } catch (parseError) {
        console.error('❌ 解析分块数据失败:', parseError);
        console.error('📄 分块详情:', chunkData.chunks.map(c => `索引${c.chunk_index}:${c.chunk_data?.length || 0}字符`));
      }
    } else {
      console.warn('⚠️ chunk_end但没有找到对应的chunk数据:', messageId);
    }
  }

  messageChunks.value = newChunks;
};

// 处理普通消息
const handleMessage = (messageData) => {
  const newMessages = [...messages.value];
  const messageId = messageData.message_id;
  if (messageData.type === "stream_end") {
    return;
  }
  // 查找是否已存在相同 message_id 的消息
  const existingIndex = newMessages.findIndex(
    msg => msg.message_id === messageId
  );

  if (existingIndex >= 0) {
    // 更新现有消息
    const existing = newMessages[existingIndex];

    // 对于工具调用结果消息，完整替换而不是合并
    if (messageData.role === 'tool' || messageData.message_type === 'tool_call_result') {
      newMessages[existingIndex] = {
        ...messageData,
        timestamp: messageData.timestamp || Date.now()
      };
    } else {
      // 对于其他消息类型，合并content
      newMessages[existingIndex] = {
        ...existing,
        ...messageData,
        content: (existing.content || '') + (messageData.content || ''),
        timestamp: messageData.timestamp || Date.now()
      };
    }
  } else {
    // 添加新消息
    newMessages.push({
      ...messageData,
      timestamp: messageData.timestamp || Date.now()
    });
    // 新消息开始时强制滚动到底部
    shouldAutoScroll.value = true
    nextTick(() => scrollToBottom(true))
  }
  console.log('📝 处理消息:', newMessages);
  messages.value = newMessages;
};

// 添加用户消息
const addUserMessage = (content) => {
  const userMessage = {
    role: 'user',
    content: content.trim(),
    message_id: Date.now().toString(),
    type: 'USER'
  };

  messages.value = [...messages.value, userMessage];
  return userMessage;
};

// 添加错误消息
const addErrorMessage = (error) => {
  const errorMessage = {
    role: 'assistant',
    content: `错误: ${error.message}`,
    message_id: Date.now().toString(),
    type: 'error',
    timestamp: Date.now()
  };

  messages.value = [...messages.value, errorMessage];
};

// 清空消息
const clearMessages = () => {
  messages.value = [];
  messageChunks.value = new Map();
};

// 停止生成
const stopGeneration = async () => {
  if (abortControllerRef.value) {
    console.log('Aborting request in stopGeneration');
    abortControllerRef.value.abort();
    isLoading.value = false;
  }

  // 调用后端interrupt接口
  if (currentSessionId.value) {
    try {
      await chatAPI.interruptSession(currentSessionId.value, '用户请求中断');
      console.log('Session interrupted successfully');
    } catch (error) {
      console.error('Error interrupting session:', error);
    }
  }
};


// 计算属性
const selectedAgentId = computed(() => selectedAgent.value?.id)

const showLoadingBubble = computed(() => {
  if (!isLoading.value) return false;
  const msgs = messages.value;
  if (!msgs || msgs.length === 0) return true;
  
  const lastMsg = msgs[msgs.length - 1];
  if (lastMsg.role !== 'assistant') return true;
  
  // Assistant message exists.
  // Hide loading if we are showing SOMETHING for this message.
  
  // Check error
  if (lastMsg.type === 'error' || lastMsg.message_type === 'error') return false;
  
  // Check tools
  if (lastMsg.tool_calls && lastMsg.tool_calls.length > 0) return false;
  
  // Check content
  if (lastMsg.content) return false;
  
  // Otherwise, we are still waiting for content
  return true;
});

// 滚动相关方法
const scrollToBottom = (force = false) => {
  if (!shouldAutoScroll.value && !force) return
  
  isAutoScrolling.value = true
  nextTick(() => {
    if (messagesListRef.value) {
      messagesListRef.value.scrollTop = messagesListRef.value.scrollHeight
      // 这里的timeout是为了防止 programmatic scroll 触发 scroll 事件导致 shouldAutoScroll 被置为 false
      setTimeout(() => {
        isAutoScrolling.value = false
      }, 100)
    } else {
      isAutoScrolling.value = false
    }
  })
}

// 检查是否滚动到底部
const isScrolledToBottom = () => {
  if (!messagesListRef.value) return true
  
  const { scrollTop, scrollHeight, clientHeight } = messagesListRef.value
  const threshold = 50 // 50px的容差
  return scrollHeight - scrollTop - clientHeight <= threshold
}

// 处理用户滚动
const handleScroll = () => {
  if (!messagesListRef.value) return
  if (isAutoScrolling.value) return
  
  // 清除之前的超时
  if (scrollTimeout.value) {
    clearTimeout(scrollTimeout.value)
  }
  
  // 标记用户正在滚动
  isUserScrolling.value = true
  
  // 检查是否滚动到底部
  const atBottom = isScrolledToBottom()
  
  if (atBottom) {
    // 用户滚动到底部，恢复自动滚动
    shouldAutoScroll.value = true
  } else {
    // 用户不在底部，禁用自动滚动
    shouldAutoScroll.value = false
  }
  
  // 设置超时，标记用户停止滚动
  scrollTimeout.value = setTimeout(() => {
    isUserScrolling.value = false
  }, 150)
}

const loadAgents = async () => {
  // 如果未登录，不加载Agent列表，避免401导致无限循环
  if (!isLoggedIn()) {
    agents.value = []
    return
  }
  try {
    const response = await agentAPI.getAgents()
    agents.value = response || []
  } catch (error) {
    console.error('Failed to load agents:', error)
    // 只有在登录状态下才提示错误，避免未登录时的干扰
    if (isLoggedIn()) {
      toast.error(t('chat.loadAgentsError'))
    }
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
const resetChat = () => {
  clearMessages()
  clearTaskAndWorkspace()
  createSession()
}

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
    // 滚动到底部（强制滚动）
    nextTick(() => {
      shouldAutoScroll.value = true
      scrollToBottom(true)
    })


  } catch (error) {
    console.error('Failed to load conversation data:', error)
    toast.error(t('chat.loadConversationError'))
  }
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
    isLoading.value = true
    shouldAutoScroll.value = true
    scrollToBottom()
    // 使用新的发送消息API
    await sendMessageApi({
      message: content,
      sessionId: sessionId,
      selectedAgent: selectedAgent.value,
      config: config.value,
      abortControllerRef: abortControllerRef,
      onMessage: (data) => {
        handleMessage(data);
      },
      onChunkMessage: (data) => {
        handleChunkMessage(data);
      },

      onComplete: async () => {
        scrollToBottom()
        isLoading.value = false
      },
      onError: (error) => {
        console.error('❌ Chat.vue消息发送错误:', error);
        addErrorMessage(error)
        isLoading.value = false
      }
    })
  } catch (error) {
    console.error('❌ Chat.vue发送消息异常:', error);
    toast.error(t('chat.sendError'))
    isLoading.value = false
  }
}


const handleToolClick = (toolExecution, result) => {

  selectedToolExecution.value = toolExecution
  toolResult.value = result
  showToolDetails.value = true
}


const downloadFile = async (item) => {
  try {
    if (currentSessionId.value) {
      await downloadWorkspaceFile(currentSessionId.value, item)
    }
  } catch (error) {
    console.error('Failed to download file:', error)
    toast.error(t('chat.downloadError'))
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
      session_id: sessionId,
      deep_thinking: config.deepThinking,
      agent_mode: config.agentMode,
      more_suggest: config.moreSuggest,
      max_loop_count: config.maxLoopCount,
      agent_id: selectedAgent.id,
    };
    const response = await chatAPI.streamChat(requestBody, abortControllerRef?.value);

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

const copyToClipboard = (text) => {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  } else {
    return new Promise((resolve, reject) => {
      try {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        if (successful) {
          resolve();
        } else {
          reject(new Error('execCommand copy failed'));
        }
      } catch (err) {
        reject(err);
      }
    });
  }
};

const handleShare = () => {
  if (!currentSessionId.value) {
    toast.error(t('chat.shareNoSession') || 'No active session to share')
    return
  }
  const shareUrl = `${window.location.origin}/share/${currentSessionId.value}`
  
  copyToClipboard(shareUrl).then(() => {
    toast.success(t('chat.shareSuccess') || 'Share link copied to clipboard')
  }).catch(err => {
    console.error('Copy failed:', err)
    toast.error(t('chat.shareFailed') || 'Failed to copy link')
  })
}

// 生命周期
onMounted(async () => {
  if (typeof window !== 'undefined') {
    window.addEventListener('user-updated', loadAgents)
  }

  // 1. 获取Agent列表
  await loadAgents()
  
  // 2. 检查URL参数是否有session_id
  const routeSessionId = route.query.session_id;
  if (routeSessionId) {
      console.log('🔗 从路由加载会话:', routeSessionId);
      await handleSessionLoad(routeSessionId);
  } else {
      // 如果没有session_id，创建一个新的
      createSession();
  }
});

// 组件卸载时清理
onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('user-updated', loadAgents)
  }
  
  if (scrollTimeout.value) {
    clearTimeout(scrollTimeout.value)
  }
})

  // 监听agents变化，自动恢复选中的智能体
watch(() => agents.value, (newAgents) => {
    console.log('🔄 agents变化，当前agents数量:', newAgents?.length || 0);
    if (newAgents && newAgents.length > 0) {
      restoreSelectedAgent(newAgents);
    }
  });

  // 监听selectedConversation变化
watch(() => props.selectedConversation, async (newConversation) => {
  if (newConversation && agents.value.length > 0) {
    await loadConversationData(newConversation)
  } else if (!newConversation) {
    // 如果没有选中的会话，重置聊天状态
    resetChat()
  }
}, { immediate: false })

// 监听路由参数变化
watch(() => route.query.session_id, (newSessionId) => {
  // 如果ID相同，不做处理
  if (newSessionId === currentSessionId.value) return;
  
  if (newSessionId) {
    console.log('🔗 路由session_id变化，加载会话:', newSessionId);
    handleSessionLoad(newSessionId);
  } else {
    // 路由参数被清空（例如点击了新对话），重置聊天
    console.log('🔗 路由session_id被清空，重置聊天');
    resetChat();
  }
});

// 监听消息变化，智能滚动到底部
watch(messages, () => {
  // 只有在应该自动滚动时才滚动
  if (shouldAutoScroll.value) {
    scrollToBottom()
  }
}, { deep: true })


</script>

