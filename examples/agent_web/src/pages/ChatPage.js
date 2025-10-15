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
  const lastRequestCompletedRef = useRef(false); // 跟踪request_completed是否已触发
  
  // 使用自定义hooks
  const {
    messages,
    setMessages,
    isLoading,
    setIsLoading,
    abortControllerRef,
    handleChunkMessage,
    handleMessage,
    addUserMessage,
    addErrorMessage,
    clearMessages,
    stopGeneration
  } = useMessages();
  
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

  // 监听config变化
  useEffect(() => {
    console.log('🔄 ChatPage中config状态变化:', config);
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
  
  // 处理选中的对话历史
  useEffect(() => {
    if (selectedConversation) {
      // 设置选中的对话内容
      setMessages(selectedConversation.messages || []);
      const newSessionId = selectedConversation.sessionId || selectedConversation.id;
      
      // 只有当session id真正发生变化时才清空任务管理和文件管理器，并中断当前请求
      if (newSessionId !== currentSessionId) {
        // 只有在有正在进行的请求时才中断
        if (abortControllerRef.current && isLoading) {
          console.log('Aborting request in selectedConversation useEffect');
          abortControllerRef.current.abort();
        }
        setCurrentSessionId(newSessionId);
        // 清空任务状态和工作空间文件，等待新数据加载
        clearTaskAndWorkspace();
      }
      
      // 设置对应的Agent
      const agent = agents.find(a => a.id === selectedConversation.agentId);
      if (agent) {
        selectAgent(agent);
      }
    } else if (!selectedConversation && currentSessionId && messages.length === 0) {
      // 只有当没有选中对话、有会话ID且没有消息时，才清空会话状态
      // 这避免了在用户发送新消息后清空消息的问题
      console.log('Clearing session state when no conversation selected and no messages');
      // 使用setTimeout避免与startNewConversation的清空逻辑冲突
      setTimeout(() => {
        clearSession();
        clearMessages();
        setShowToolDetails(false);
        setSelectedToolExecution(null);
        clearTaskAndWorkspace();
      }, 10);
    }
  }, [selectedConversation, agents, currentSessionId, clearTaskAndWorkspace, selectAgent, clearSession, clearMessages]);
  
  // 初始化时恢复选中的Agent
  useEffect(() => {
    if (agents.length > 0) {
      restoreSelectedAgent(agents);
    }
  }, [agents, restoreSelectedAgent]);
  
  const startNewConversation = () => {
    // 如果当前有会话ID和消息，保存到历史对话中
    if (currentSessionId && messages.length > 0 && selectedAgent) {
      // 获取第一条用户消息作为标题
      const firstUserMessage = messages.find(msg => msg.role === 'user');
      const title = firstUserMessage 
        ? firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '')
        : t('chat.untitledConversation');
      
      // 添加到对话记录
      if (onAddConversation) {
        onAddConversation({
          id: currentSessionId,
          title: title,
          agentId: selectedAgent.id,
          agentName: selectedAgent.name,
          messages: messages,
          sessionId: currentSessionId,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString()
        });
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
  };
  
  // 停止生成处理函数
  const handleStopGeneration = useCallback(() => {
    stopGeneration(currentSessionId);
  }, [stopGeneration, currentSessionId]);
  
  // 保存当前会话状态
  const saveCurrentConversation = useCallback(() => {
    console.log('saveCurrentConversation called:', {
      currentSessionId,
      messagesLength: messages.length,
      selectedAgent: selectedAgent?.name,
      onAddConversation: !!onAddConversation
    });
    
    if (currentSessionId && messages.length > 0 && selectedAgent && onAddConversation) {
      // 获取第一条用户消息作为标题
      const firstUserMessage = messages.find(msg => msg.role === 'user');
      const title = firstUserMessage 
        ? firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '')
        : '未命名对话';
      
      console.log('Saving conversation with title:', title);
      
      // 添加对话记录
      onAddConversation({
        id: currentSessionId,
        title: title,
        agentId: selectedAgent.id,
        agentName: selectedAgent.name,
        messages: messages,
        sessionId: currentSessionId,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      });
      
      console.log('Conversation saved successfully');
    } else {
      console.log('Conversation not saved - missing requirements');
    }
  }, [currentSessionId, messages, selectedAgent, onAddConversation]);
  
  // 自动保存函数 - 统一的保存逻辑
  const triggerAutoSave = useCallback((reason = 'unknown', shouldUpdateTasks = true) => {
    if (currentSessionId && messages.length > 0 && selectedAgent) {
      console.log(`💾 Auto-save triggered by: ${reason}, messages count: ${messages.length}`);
      
      const firstUserMessage = messages.find(msg => msg.role === 'user');
      const title = firstUserMessage 
        ? firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '')
        : '未命名对话';
      
      if (onAddConversation) {
        onAddConversation({
          id: currentSessionId,
          title: title,
          agentId: selectedAgent.id,
          agentName: selectedAgent.name,
          messages: messages,
          sessionId: currentSessionId,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString()
        });
        console.log(`💾 Auto-save completed for reason: ${reason}`);
        
        // 只在需要时更新任务状态和工作空间文件
        if (shouldUpdateTasks) {
          console.log(`🔄 会话保存完成，同步更新任务状态和工作空间, 原因: ${reason}`);
          checkForUpdates(messages, currentSessionId, `session_saved_${reason}`);
        }
      }
    }
  }, [currentSessionId, messages, selectedAgent, onAddConversation, checkForUpdates]);
  
  // 监听消息变化 - 只有当消息ID真正发生变化时才触发保存
  useEffect(() => {
    if (messages.length > 0 && currentSessionId && selectedAgent && onAddConversation) {
      // 获取最新消息的ID用于日志
      const latestMessage = messages[messages.length - 1];
      const latestMessageId = latestMessage?.message_id || latestMessage?.id || 'no-id';
      
      console.log(`🔍 消息变化检测: 消息数量=${messages.length}, 最新消息ID=${latestMessageId}, 上次保存ID=${lastSavedMessageIdRef.current}, 会话ID=${currentSessionId}`);
      
      // 只有当消息ID真正发生变化时才保存
      if (latestMessageId !== lastSavedMessageIdRef.current) {
        console.log(`✅ 检测到新消息ID变化: ${lastSavedMessageIdRef.current} -> ${latestMessageId}，触发保存`);
        
        // 立即更新保存的消息ID，避免重复触发
        lastSavedMessageIdRef.current = latestMessageId;
        
        // 延迟保存，确保消息完全更新
        const saveTimer = setTimeout(() => {
          console.log(`💾 Auto-save triggered by: message_id_change, messages count: ${messages.length}, latest message ID: ${latestMessageId}`);
          
          const firstUserMessage = messages.find(msg => msg.role === 'user');
          const title = firstUserMessage 
            ? firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '')
            : '未命名对话';
          
          onAddConversation({
            id: currentSessionId,
            title: title,
            agentId: selectedAgent.id,
            agentName: selectedAgent.name,
            messages: messages,
            sessionId: currentSessionId,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
          });
          
          console.log(`💾 Auto-save completed for reason: message_id_change, latest message ID: ${latestMessageId}`);
          
          // 单独检查任务状态更新
          checkForUpdates(messages, currentSessionId, 'message_id_change');
        }, 300);
        
        return () => clearTimeout(saveTimer);
      } else {
        console.log(`⏭️ 消息ID未变化，跳过保存: ${latestMessageId}`);
      }
    }
  }, [messages.length, currentSessionId, selectedAgent?.id]); // 进一步优化依赖数组，移除onAddConversation避免频繁触发
  
  // 监听请求结束 - 只有当loading从true变为false时才触发保存
  useEffect(() => {
    if (isLoading) {
      // 当开始加载时，重置标记
      lastRequestCompletedRef.current = false;
    } else if (!isLoading && messages.length > 0 && currentSessionId && !lastRequestCompletedRef.current) {
      // 只有当loading从true变为false且未触发过时才保存
      lastRequestCompletedRef.current = true;
      // 延迟保存，确保状态完全更新
      const saveTimer = setTimeout(() => {
        console.log('🏁 请求完成，触发最终保存和任务状态更新');
        triggerAutoSave('request_completed', true);
      }, 500);
      
      return () => clearTimeout(saveTimer);
    }
  }, [isLoading, currentSessionId, messages.length]); // 移除triggerAutoSave依赖，避免重复触发
  
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
    
    // 如果没有会话ID，创建新的会话ID
    let sessionId = currentSessionId;
    if (!sessionId) {
      sessionId = createSession();
      console.log('🆕 创建新会话ID:', sessionId);
    }
    
    // 添加用户消息
    const userMessage = addUserMessage(messageText);
    console.log('👤 添加用户消息:', userMessage.message_id);
    setIsLoading(true);
    
    // 立即触发保存 - 用户发送消息时
    setTimeout(() => {
      console.log('📤 用户发送消息，准备保存会话和更新任务状态');
      triggerAutoSave('user_message_sent');
    }, 100);
    
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
          // 请求完成时的保存将由useEffect监听isLoading变化自动触发
        }
      });
    } catch (error) {
      console.error('❌ ChatPage发送消息异常:', error);
      addErrorMessage(error);
      setIsLoading(false);
    }
  }, [sendMessage, isLoading, selectedAgent, currentSessionId, createSession, addUserMessage, setIsLoading, handleMessage, handleChunkMessage, addErrorMessage, triggerAutoSave, config]);
  
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