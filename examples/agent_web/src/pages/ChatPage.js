import React, { useState, useRef, useEffect, useImperativeHandle, forwardRef, useCallback } from 'react';
import { Bot, Settings, List, Folder } from 'lucide-react';
import './ChatPage.css';
import { useLanguage } from '../contexts/LanguageContext';

// 导入自定义hooks
import { useMessages } from '../hooks/useMessages';
import { useSession } from '../hooks/useSession';
import { useTaskManager } from '../hooks/useTaskManager';
import { useChatAPI } from '../hooks/useChatAPI';

// 导入组件
import MessageRenderer from '../components/chat/MessageRenderer';
import TaskStatusPanel from '../components/chat/TaskStatusPanel';
import WorkspacePanel from '../components/chat/WorkspacePanel';
import ConfigPanel from '../components/chat/ConfigPanel';
import MessageInput from '../components/chat/MessageInput';

const ChatPage = forwardRef(({ agents, onAddConversation, onUpdateConversation, tools, selectedConversation, onClearSelectedConversation }, ref) => {
  const { t } = useLanguage();
  
  // UI状态
  const [showSettings, setShowSettings] = useState(false);
  const [showTaskStatus, setShowTaskStatus] = useState(false);
  const [showWorkspace, setShowWorkspace] = useState(false);
  const [selectedToolExecution, setSelectedToolExecution] = useState(null);
  const [showToolDetails, setShowToolDetails] = useState(false);
  const messagesEndRef = useRef(null);
  const lastSavedMessageIdRef = useRef(null); // 跟踪上次保存的消息ID

  
  // 先定义 session hook 获取 currentSessionId
  const {
    currentSessionId,
    setCurrentSessionId,
    selectedAgent,
    config,
    createSession,
    clearSession,
    updateConfig,
    selectAgent,
    restoreSelectedAgent
  } = useSession(agents);

  // 添加标志来标识是否正在恢复历史对话
  const [isRestoringHistory, setIsRestoringHistory] = useState(false);
  
  // 添加ref来防止重复执行恢复历史对话的逻辑
  const lastSelectedConversationRef = useRef(null);

  // Token 使用信息更新回调
  const handleUpdateConversationTokenUsage = useCallback((tokenUsageData) => {
    console.log('🔄 handleUpdateConversationTokenUsage 被调用', {
      currentSessionId,
      hasOnUpdateConversation: !!onUpdateConversation,
      tokenUsageData: tokenUsageData,
      isRestoringHistory: isRestoringHistory
    });
    
    if (currentSessionId && onUpdateConversation && !isRestoringHistory) {
      // 直接使用 currentSessionId 作为对话ID进行更新
      // 因为在 addConversation 中，对话的 id 就是 sessionId
      console.log('📊 更新对话的 tokenUsage（累加模式）', {
        conversationId: currentSessionId,
        totalTokens: tokenUsageData.total_info?.total_tokens
      });
      onUpdateConversation(currentSessionId, { tokenUsage: tokenUsageData }, true); // shouldAccumulate = true
    } else if (isRestoringHistory) {
      console.log('⏭️ 恢复历史对话中，跳过 tokenUsage 累加');
    } else {
      console.warn('⚠️ 无法更新 tokenUsage：缺少 sessionId 或 onUpdateConversation 回调');
    }
  }, [currentSessionId, onUpdateConversation, isRestoringHistory]);





  // useMessages hook 将在 handleMessageChange 定义后调用

  // 监听config变化
  useEffect(() => {
    // console.log('🔄 ChatPage中config状态变化:', config);
  }, [config]); 
  const {
    taskStatus,
    workspaceFiles,
    workspacePath,
    expandedTasks,
    downloadFile,
    toggleTaskExpanded,
    updateTaskAndWorkspace,
    clearTaskAndWorkspace,
    checkForUpdates
  } = useTaskManager();
  
  const { sendMessage } = useChatAPI();
  
  // 暴露方法给父组件
  useImperativeHandle(ref, () => ({
    startNewConversation
  }));
  
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };



  // 这些回调将在useMessages之后重新定义

  // 这个 useEffect 将在 useMessages 调用之后重新定义
  
  // 初始化时恢复选中的Agent
  useEffect(() => {
    if (agents.length > 0) {
      restoreSelectedAgent(agents);
    }
  }, [agents, restoreSelectedAgent]);
  

  

  

  
  // 使用 useRef 来存储消息变化回调，避免循环依赖
  const messageChangeCallbackRef = useRef(null);
  
  // 使用自定义hooks
  const {
    messages,
    setMessages,
    isLoading,
    setIsLoading,
    tokenUsage,
    setTokenUsage,
    abortControllerRef,
    handleChunkMessage,
    handleMessage,
    addUserMessage,
    addErrorMessage,
    clearMessages,
    stopGeneration
  } = useMessages(handleUpdateConversationTokenUsage, isRestoringHistory);
  
  // 开始新对话函数
  const startNewConversation = useCallback(() => {
    // 如果当前有会话ID和消息，保存到历史对话中
    if (currentSessionId && messages.length > 0 && selectedAgent) {
      // 获取第一条用户消息作为标题
      const firstUserMessage = messages.find(msg => msg.role === 'user');
      const title = firstUserMessage 
        ? firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '')
        : t('chat.untitledConversation');
      
      // 添加到对话记录
      if (onAddConversation) {
        const conversationData = {
          id: currentSessionId,
          title: title,
          agentId: selectedAgent.id,
          agentName: selectedAgent.name,
          messages: messages,
          sessionId: currentSessionId,
          // 如果是恢复历史对话，保留原有时间戳；否则创建新时间戳
          createdAt: isRestoringHistory && selectedConversation?.createdAt 
            ? selectedConversation.createdAt 
            : new Date().toISOString(),
          updatedAt: isRestoringHistory && selectedConversation?.updatedAt 
            ? selectedConversation.updatedAt 
            : new Date().toISOString()
        };
        
        // 总是保存 tokenUsage（如果存在的话）
        if (tokenUsage) {
          conversationData.tokenUsage = tokenUsage;
          console.log('💾 开始新对话时保存 tokenUsage', {
            totalTokens: tokenUsage.total_info?.total_tokens
          });
        }
        
        // 在恢复历史对话时不累加tokenUsage，避免重复计算
        onAddConversation(conversationData, false, !isRestoringHistory);
      }
    }
    
    // 清空当前页面状态
    clearMessages();
    clearSession();
    setShowToolDetails(false);
    setSelectedToolExecution(null);
    // 只有在有正在进行的请求时才中断
    if (abortControllerRef.current && isLoading) {
      console.log('Aborting request in startNewConversation');
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = null;
  }, [currentSessionId, messages, selectedAgent, t, isRestoringHistory, selectedConversation, onAddConversation, tokenUsage, clearMessages, clearSession, setShowToolDetails, setSelectedToolExecution, abortControllerRef, isLoading]);
   
  // 停止生成处理函数
  const handleStopGeneration = useCallback(() => {
    stopGeneration(currentSessionId);
  }, [stopGeneration, currentSessionId]);

  // 处理选中的对话历史
  useEffect(() => {
    if (selectedConversation) {
      // 检查是否是同一个对话，避免重复执行
      const conversationKey = `${selectedConversation.id}_${selectedConversation.sessionId}`;
      if (lastSelectedConversationRef.current === conversationKey) {
        console.log('🔄 跳过重复的对话恢复:', conversationKey);
        return;
      }
      
      // 更新ref记录当前对话
      lastSelectedConversationRef.current = conversationKey;
      
      // 立即设置恢复历史标志，并使用 flushSync 确保状态立即更新
      setIsRestoringHistory(true);
      
      // 使用 setTimeout 确保 isRestoringHistory 状态已经更新
      setTimeout(() => {
        console.log('🔄 开始恢复历史对话，isRestoringHistory=true');
        
        // 设置选中的对话内容
         const conversationMessages = selectedConversation.messages || [];
         setMessages(conversationMessages);
        
        // 设置 lastSavedMessageIdRef 为最新消息的ID，避免触发重复保存
        const latestMessageId = conversationMessages.length > 0 ? conversationMessages[conversationMessages.length - 1].message_id : null;
        if (latestMessageId) {
          lastSavedMessageIdRef.current = latestMessageId;
        }
        
        // 恢复 tokenUsage - 直接设置，不使用函数形式避免累加
        if (selectedConversation.tokenUsage) {
          console.log('🔄 恢复对话的 tokenUsage:', selectedConversation.tokenUsage);
          setTokenUsage(selectedConversation.tokenUsage);
        } else {
          console.log('⚠️ 选中的对话没有 tokenUsage 信息，重置为初始状态');
          setTokenUsage({ total_info: {}, per_step_info: [] });
        }
        
        // 设置会话ID
        setCurrentSessionId(selectedConversation.sessionId);
        
        // 中断当前请求
        if (abortControllerRef.current) {
          abortControllerRef.current.abort();
        }
        
        // 清空任务和工作空间
        clearTaskAndWorkspace();
        
        // 设置对应的Agent
        if (selectedConversation.agentId && agents) {
          const agent = agents.find(a => a.id === selectedConversation.agentId);
          if (agent) {
            selectAgent(agent);
          }
        }
        
        // 不在这里重置 isRestoringHistory，而是在用户发送消息时重置
      }, 50);
    } else {
      // 清理ref记录
      lastSelectedConversationRef.current = null;
      
      if (!messages || messages.length === 0) {
        clearSession();
      }
    }
  }, [selectedConversation, agents, currentSessionId, clearTaskAndWorkspace, selectAgent, clearSession, messages, setMessages]);
   
  // 使用 useRef 来存储最新的 tokenUsage，避免 saveConversation 函数重新创建
  const tokenUsageRef = useRef(tokenUsage);
  tokenUsageRef.current = tokenUsage;
  
  // 添加保存状态跟踪，避免重复保存
  const lastSavedMessagesCountRef = useRef(0);
  const saveTimeoutRef = useRef(null);
  
  // 简单的保存函数
  const saveConversation = useCallback(() => {
    // 如果正在恢复历史对话，跳过保存
    if (isRestoringHistory) {
      console.log('🚫 正在恢复历史对话，跳过保存操作');
      return;
    }
    
    // 检查是否需要保存（消息数量是否有变化）
    if (messages.length === lastSavedMessagesCountRef.current) {
      console.log('⏭️ 消息数量未变化，跳过保存', {
        currentCount: messages.length,
        lastSavedCount: lastSavedMessagesCountRef.current
      });
      return;
    }
    
    // 检查保存条件
    if (currentSessionId && messages.length > 0 && selectedAgent && onAddConversation) {
      console.log(`💾 保存对话, messages count: ${messages.length}`);
      
      const firstUserMessage = messages.find(msg => msg.role === 'user');
      const title = firstUserMessage 
        ? firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '')
        : '未命名对话';
      
      const conversationData = {
        id: currentSessionId,
        title: title,
        agentId: selectedAgent.id,
        agentName: selectedAgent.name,
        messages: messages,
        sessionId: currentSessionId,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      
      // 包含 tokenUsage，使用 ref 获取最新值
      if (tokenUsageRef.current) {
        conversationData.tokenUsage = tokenUsageRef.current;
        console.log('💾 保存时包含 tokenUsage', {
          totalTokens: tokenUsageRef.current.total_info?.total_tokens
        });
      }
      
      // 保存对话数据 - 使用覆盖模式而不是累加模式，避免重复累加tokenUsage
      onAddConversation(conversationData, false, false);
      
      // 更新已保存的消息数量
      lastSavedMessagesCountRef.current = messages.length;
      console.log('💾 对话保存完成');
    }
  }, [currentSessionId, messages, selectedAgent, onAddConversation, isRestoringHistory]);
  
  // 监听messages变化，自动保存
  useEffect(() => {
    // 严格的保存条件检查：
    // 1. 消息数量大于0
    // 2. 不在恢复历史对话状态（发送消息时的加载状态不应阻止保存）
    // 3. 有当前会话ID
    // 4. 有选中的Agent
    if (messages.length > 0 && 
        !isRestoringHistory && 
        currentSessionId && 
        selectedAgent) {
      
      console.log('🔍 检查是否需要保存对话', {
        messagesLength: messages.length,
        isRestoringHistory,
        currentSessionId,
        hasSelectedAgent: !!selectedAgent
      });
      
      // 清除之前的定时器
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
      
      // 延迟保存，避免频繁保存
      saveTimeoutRef.current = setTimeout(() => {
        console.log('⏰ 定时器触发，准备保存对话');
        saveConversation();
        saveTimeoutRef.current = null;
      }, 1000); // 增加延迟时间到1秒
      
      return () => {
        if (saveTimeoutRef.current) {
          clearTimeout(saveTimeoutRef.current);
          saveTimeoutRef.current = null;
        }
      };
    } else {
      console.log('🚫 跳过保存，条件不满足', {
        messagesLength: messages.length,
        isRestoringHistory,
        currentSessionId,
        hasSelectedAgent: !!selectedAgent
      });
    }
  }, [messages, saveConversation, isRestoringHistory, currentSessionId, selectedAgent]);

  // 优化任务管理器按钮点击处理
  const handleTaskStatusToggle = useCallback(() => {
    setShowTaskStatus(prev => {
      const newValue = !prev;
      if (newValue) {
        // 每次打开时更新任务状态
        checkForUpdates(messages, currentSessionId);
      }
      return newValue;
    });
  }, [currentSessionId, checkForUpdates, messages]);

  // 优化工作空间按钮点击处理
  const handleWorkspaceToggle = useCallback(() => {
    setShowWorkspace(prev => {
      const newValue = !prev;
      if (newValue && currentSessionId) {
        // 每次打开时更新工作空间文件
        checkForUpdates(messages, currentSessionId);
      }
      return newValue;
    });
  }, [currentSessionId, checkForUpdates, messages]);
  
  useEffect(() => {
    scrollToBottom();
  }, [messages]);
  
  // 处理工具点击
  const handleToolClick = useCallback((toolCall, toolResult) => {
    console.log('🔧 Tool click debug info:');
    console.log('toolCall:', toolCall);
    console.log('toolCall.function:', toolCall.function);
    console.log('toolCall.function.arguments:', toolCall.function?.arguments);
    console.log('toolCall.function.arguments type:', typeof toolCall.function?.arguments);
    
    let parsedArguments = {};
    
    // 安全解析JSON参数
    if (toolCall.function?.arguments) {
      try {
        console.log('🔍 Attempting to parse arguments:', toolCall.function.arguments);
        parsedArguments = JSON.parse(toolCall.function.arguments);
        console.log('✅ Successfully parsed arguments:', parsedArguments);
      } catch (error) {
        console.error('❌ Failed to parse tool arguments:', error);
        console.error('Raw arguments content:', JSON.stringify(toolCall.function.arguments));
        console.error('Arguments length:', toolCall.function.arguments.length);
        // 如果解析失败，尝试将其作为字符串处理
        parsedArguments = { raw: toolCall.function.arguments };
      }
    }
    
    setSelectedToolExecution({
      name: toolCall.function?.name || 'Unknown Tool',
      arguments: parsedArguments,
      result: toolResult?.content || toolResult?.show_content || '暂无结果'
    });
    setShowToolDetails(true);
  }, []);
  
  const handleSendMessage = useCallback(async (messageText) => {
    if (!messageText.trim() || isLoading || !selectedAgent) return;
    
    console.log('🚀 开始发送消息:', messageText.substring(0, 100) + (messageText.length > 100 ? '...' : ''));
    
    // 用户开始发送消息时，重置恢复历史状态
    if (isRestoringHistory) {
      console.log('🔄 用户发送消息，重置 isRestoringHistory=false');
      setIsRestoringHistory(false);
    }
    
    // 如果没有会话ID，创建新的会话ID
    let sessionId = currentSessionId;
    if (!sessionId) {
      sessionId = createSession();
      console.log('🆕 创建新会话ID:', sessionId);
    }
    
    // 添加用户消息（会自动触发保存回调）
    const userMessage = addUserMessage(messageText);
    console.log('👤 添加用户消息:', userMessage.message_id);
    setIsLoading(true);
    
    try {
      // 添加配置状态日志
      console.log('📤 ChatPage发送消息时的config状态:', config);
      console.log('📤 ChatPage中config的类型:', typeof config);
      console.log('📤 ChatPage中config的属性:', Object.keys(config || {}));
      
      console.log('📡 准备调用sendMessage API，参数:', {
        messageLength: messageText.length,
        sessionId,
        agentName: selectedAgent.name,
        configKeys: Object.keys(config || {})
      });
      
      // 使用新的发送消息API
      await sendMessage({
        message: messageText,
        sessionId: sessionId,
        selectedAgent,
        config,
        abortControllerRef,
        onMessage: (data) => {
          console.log('📨 ChatPage收到普通消息回调:', data.type || data.message_type, data.message_id);
          handleMessage(data);
        },
        onChunkMessage: (data) => {
          console.log('🧩 ChatPage收到分块消息回调:', data.type, data.message_id);
          handleChunkMessage(data);
        },
        onError: (error) => {
          console.error('❌ ChatPage消息发送错误:', error);
          addErrorMessage(error);
          setIsLoading(false);
        },
        onComplete: () => {
          console.log('✅ ChatPage消息请求完成');
          setIsLoading(false);
          // 最终保存，确保所有消息和tokenUsage都已处理完成，并更新任务状态
          setTimeout(() => {
            console.log('🏁 后端响应完成，触发最终保存和任务状态更新');
            saveConversation();
          }, 500);
        }
      });
    } catch (error) {
      console.error('❌ ChatPage发送消息异常:', error);
      addErrorMessage(error);
      setIsLoading(false);
    }
  }, [sendMessage, isLoading, selectedAgent, currentSessionId, createSession, addUserMessage, setIsLoading, handleMessage, handleChunkMessage, addErrorMessage, config]);
  
  // 删除handleKeyPress，由MessageInput组件处理
  
  return (
    <div className="chat-page">
      <div className="chat-header">
        <div className="chat-title">
          <h2>{t('chat.title')}</h2>
          {selectedAgent && (
            <span className="agent-name">{t('chat.current')}: {selectedAgent.name}</span>
          )}
        </div>
        <div className="chat-controls">
          <select 
            className="select agent-select"
            value={selectedAgent?.id || ''}
            onChange={(e) => {
              const agent = agents.find(a => a.id === e.target.value);
              selectAgent(agent);
            }}
          >
            {agents.map(agent => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
          <button 
            className="btn btn-ghost"
            onClick={() => setShowSettings(!showSettings)}
          >
            <Settings size={16} />
          </button>
          <button 
            className="btn btn-ghost"
            onClick={handleTaskStatusToggle}
            title={t('chat.taskManager')}
          >
            <List size={16} />
          </button>
          <button 
            className="btn btn-ghost"
            onClick={handleWorkspaceToggle}
            title={t('chat.workspace')}
          >
            <Folder size={16} />
          </button>

        </div>
      </div>
      
      <div className={`chat-container ${showToolDetails || showTaskStatus || showWorkspace || showSettings ? 'split-view' : ''}`}>
        <div className="chat-messages">
          {messages.length === 0 ? (
            <div className="empty-state">
              <Bot size={48} className="empty-icon" />
              <h3>{t('chat.emptyTitle')}</h3>
              <p>{t('chat.emptyDesc')}</p>
            </div>
          ) : (
            <div className="messages-list">
              {messages.map((message, index) => (
                <MessageRenderer
                  key={message.id || index}
                  message={message}
                  onDownloadFile={downloadFile}
                  onToolClick={handleToolClick}
                  messages={messages}
                  messageIndex={index}
                  isRestoringHistory={isRestoringHistory}
                />
              ))}
              {isLoading && (
                <div className="loading-indicator">
                  <div className="loading-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              )}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        
        {showToolDetails && selectedToolExecution && (
          <div className="tool-details-panel">
            <div className="tool-details-header">
              <h3>{t('chat.toolDetails')}</h3>
              <button 
                className="btn btn-ghost"
                onClick={() => setShowToolDetails(false)}
              >
                ×
              </button>
            </div>
            <div className="tool-details-content">
              <div className="tool-section">
                <h4>{t('chat.toolName')}</h4>
                <p>{selectedToolExecution.name}</p>
              </div>
              <div className="tool-section">
                <h4>{t('chat.toolParams')}</h4>
                <pre className="tool-code">
                  {JSON.stringify(selectedToolExecution.arguments, null, 2)}
                </pre>
              </div>
              <div className="tool-section">
                <h4>{t('chat.toolResult')}</h4>
                <pre className="tool-code">
                  {selectedToolExecution.result ? 
                    (typeof selectedToolExecution.result === 'string' ? 
                      selectedToolExecution.result : 
                      JSON.stringify(selectedToolExecution.result, null, 2)
                    ) : t('chat.noResult')
                  }
                </pre>
              </div>
            </div>
          </div>
        )}
        
        {showTaskStatus && (
          <TaskStatusPanel
            taskStatus={taskStatus}
            expandedTasks={expandedTasks}
            onToggleTask={toggleTaskExpanded}
            onClose={() => setShowTaskStatus(false)}
          />
        )}
        
        {showWorkspace && (
          <WorkspacePanel
            currentSessionId={currentSessionId}
            workspaceFiles={workspaceFiles}
            onDownloadFile={downloadFile}
            onClose={() => setShowWorkspace(false)}
          />
        )}
        
        {showSettings && (
          <ConfigPanel
            agents={agents}
            selectedAgent={selectedAgent}
            onAgentSelect={selectAgent}
            config={config}
            onConfigChange={updateConfig}
            onClose={() => setShowSettings(false)}
          />
        )}
      </div>
      
      <MessageInput
        isLoading={isLoading}
        onSendMessage={handleSendMessage}
        onStopGeneration={handleStopGeneration}
      />
    </div>
  );
});

export default ChatPage;