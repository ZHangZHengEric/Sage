import React, { useState, useImperativeHandle, forwardRef, useEffect, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { Message, ChatSettings, ToolCall } from '../types/chat';
import { useChatMessages } from '../hooks/useChatMessages';
import { useChatHistory } from '../hooks/useChatHistory';
import { useSystem } from '../context/SystemContext';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import ToolDetailPanel from './ToolDetailPanel';
import FileViewer from './FileViewer';
import { ToolCallData } from '../types/toolCall';
import { ChatHistoryItem } from '../hooks/useChatHistory';

interface ChatInterfaceProps {
  currentChatId?: string;
  loadedMessages?: ChatHistoryItem['messages'] | null;
  loadedSettings?: ChatHistoryItem['settings'] | null;
}

export interface ChatInterfaceRef {
  startNewChat: () => void;
  loadChat: (messages: ChatHistoryItem['messages'], settings?: ChatSettings) => void;
}

const ChatInterface = forwardRef<ChatInterfaceRef, ChatInterfaceProps>(
  ({ currentChatId, loadedMessages, loadedSettings }, ref) => {
  const { state } = useSystem();
  const [inputValue, setInputValue] = useState('');
    const [useDeepThink, setUseDeepThink] = useState(false);
    const [useMultiAgent, setUseMultiAgent] = useState(false);
    const [sessionId] = useState(uuidv4());
    const [toolPanelVisible, setToolPanelVisible] = useState(false);
    const [selectedToolCall, setSelectedToolCall] = useState<ToolCallData | null>(null);
    const [isLoadingHistory, setIsLoadingHistory] = useState(false);
    const [lastSavedMessageCount, setLastSavedMessageCount] = useState(0);
    
    // 用于处理分块JSON的状态
    const [chunkBuffer, setChunkBuffer] = useState<Map<string, {chunks: string[], totalChunks: number, receivedChunks: number}>>(new Map());
    
    // 用于中断对话的AbortController
    const [currentAbortController, setCurrentAbortController] = useState<AbortController | null>(null);

    // 文件查看器状态
    const [fileViewerVisible, setFileViewerVisible] = useState(false);
    const [selectedFile, setSelectedFile] = useState<{ url: string; name: string } | null>(null);

    // 处理分块JSON的函数
    const handleJsonChunk = (chunkData: any) => {
      const { chunk_id, chunk_index, total_chunks, chunk_data, chunk_size, checksum, is_final } = chunkData;
      const baseId = chunk_id.split('_')[0]; // 提取基础ID
      
      // 验证校验和
      if (checksum !== undefined) {
        const expectedChecksum = hash(chunk_data) % 1000000;
        if (expectedChecksum !== checksum) {
          console.error(`❌ [CHUNK] 校验和不匹配: 期望 ${checksum}, 实际 ${expectedChecksum}`);
          return;
        }
      }
      
      setChunkBuffer(prev => {
        const newBuffer = new Map(prev);
        
        if (!newBuffer.has(baseId)) {
          newBuffer.set(baseId, {
            chunks: new Array(total_chunks).fill(''),
            totalChunks: total_chunks,
            receivedChunks: 0
          });
        }
        
        const buffer = newBuffer.get(baseId)!;
        
        // 如果这个chunk还没有接收过
        if (buffer.chunks[chunk_index] === '') {
          buffer.chunks[chunk_index] = chunk_data;
          buffer.receivedChunks++;
          
          console.log(`📦 [CHUNK] 接收分块 ${chunk_index + 1}/${total_chunks} (${chunk_data.length} 字符) ✓`);
          
          // 检查是否所有分块都已接收
          if (buffer.receivedChunks === buffer.totalChunks) {
            console.log(`✅ [CHUNK] 所有分块接收完成，重组JSON`);
            
            // 重组完整JSON
            const completeJson = buffer.chunks.join('');
            
            try {
              const completeData = JSON.parse(completeJson);
              console.log(`🔄 [CHUNK] 重组JSON成功: ${completeJson.length} 字符`);
              
              // 处理重组后的完整消息
              handleMessageChunk(completeData);
              
              // 清理缓冲区
              newBuffer.delete(baseId);
            } catch (error) {
              console.error(`❌ [CHUNK] 重组JSON失败:`, error);
              console.error(`❌ [CHUNK] 完整JSON前500字符:`, completeJson.substring(0, 500));
              
              // 保存到localStorage用于调试
              localStorage.setItem('failed_chunk_json', completeJson);
              console.log('💾 失败的JSON已保存到localStorage: failed_chunk_json');
            }
          }
        } else {
          console.log(`⚠️ [CHUNK] 重复接收分块 ${chunk_index + 1}/${total_chunks}，忽略`);
        }
        
        return newBuffer;
      });
    };

    // 简单的hash函数，用于校验
    const hash = (str: string): number => {
      let hash = 0;
      for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // 转换为32位整数
      }
      return Math.abs(hash);
    };

    const {
      messages,
      isLoading,
      setIsLoading,
      addLoadingMessage,
      addUserMessage,
      handleMessageChunk,
      addErrorMessage,
      clearMessages,
      setMessages
    } = useChatMessages();

    const { saveChat } = useChatHistory();

    // 生成或使用聊天ID
    const [chatId] = useState(currentChatId || uuidv4());

    // 监听loadedMessages变化，自动加载历史消息
    useEffect(() => {
      if (loadedMessages && loadedMessages.length > 0) {
        console.log('📚 加载历史消息:', loadedMessages.length, '条', '设置:', loadedSettings);
        setIsLoadingHistory(true);
        // 完整恢复Message对象，包括所有Date字段
        setMessages(loadedMessages.map(msg => ({
          ...msg,
          timestamp: new Date(msg.timestamp),
          startTime: msg.startTime ? new Date(msg.startTime) : undefined,
          endTime: msg.endTime ? new Date(msg.endTime) : undefined
        })));
        
        // 恢复设置状态
        if (loadedSettings) {
          setUseDeepThink(loadedSettings.useDeepThink);
          setUseMultiAgent(loadedSettings.useMultiAgent);
          console.log('🔧 恢复设置状态:', loadedSettings);
        }
        
        setInputValue('');
        setIsLoading(false);
        // 延迟重置标志，确保不会触发自动保存
        setTimeout(() => {
          setIsLoadingHistory(false);
          // 重置保存计数器
          const messageCount = loadedMessages.filter(msg => msg.type !== 'loading').length;
          setLastSavedMessageCount(messageCount);
        }, 100);
      }
    }, [loadedMessages, loadedSettings, setMessages, setIsLoading]);

  // 暴露给父组件的方法
  useImperativeHandle(ref, () => ({
    startNewChat: () => {
      clearMessages();
      setInputValue('');
      setIsLoading(false);
      setIsLoadingHistory(false);
      setLastSavedMessageCount(0);
      // 关闭工具面板
      setToolPanelVisible(false);
      setSelectedToolCall(null);
    },
    loadChat: (chatMessages: ChatHistoryItem['messages'], settings?: ChatSettings) => {
      console.log('📚 通过ref加载历史消息:', chatMessages.length, '条', '设置:', settings);
      setIsLoadingHistory(true);
      // 完整恢复Message对象，包括所有Date字段
      setMessages(chatMessages.map(msg => ({
        ...msg,
        timestamp: new Date(msg.timestamp),
        startTime: msg.startTime ? new Date(msg.startTime) : undefined,
        endTime: msg.endTime ? new Date(msg.endTime) : undefined
      })));
      
      // 恢复设置状态
      if (settings) {
        setUseDeepThink(settings.useDeepThink);
        setUseMultiAgent(settings.useMultiAgent);
        console.log('🔧 恢复设置状态:', settings);
      }
      
      setInputValue('');
      setIsLoading(false);
      // 关闭工具面板
      setToolPanelVisible(false);
      setSelectedToolCall(null);
      // 延迟重置标志，确保不会触发自动保存
      setTimeout(() => {
        setIsLoadingHistory(false);
        // 重置保存计数器
        const messageCount = chatMessages.filter(msg => msg.type !== 'loading').length;
        setLastSavedMessageCount(messageCount);
      }, 100);
    }
  }));

        // 保存对话历史
    const saveChatHistory = useCallback(() => {
      // 如果正在加载历史记录，不要保存
      if (isLoadingHistory) {
        console.log('🚫 正在加载历史记录，跳过保存');
        return;
      }
      
    if (messages.length > 0) {
        // 只保存非loading消息，保存完整的Message对象
        const messagesToSave = messages
          .filter(msg => msg.type !== 'loading');
        
        if (messagesToSave.length > 0) {
          const currentSettings: ChatSettings = { useDeepThink, useMultiAgent };
          saveChat(chatId, messagesToSave, currentSettings);
          console.log('💾 对话历史已保存:', chatId, messagesToSave.length, '条消息', '设置:', currentSettings);
        }
      }
    }, [messages, chatId, saveChat, isLoadingHistory, useDeepThink, useMultiAgent]);

    // 监听消息变化，自动保存对话历史
    useEffect(() => {
      // 如果正在加载历史记录，不要保存
      if (isLoadingHistory) {
        console.log('🚫 正在加载历史记录，跳过自动保存');
        return;
      }
      
      // 只有消息数量发生变化时才保存，避免因设置变化而重复保存
      const currentMessageCount = messages.filter(msg => msg.type !== 'loading').length;
      if (currentMessageCount === lastSavedMessageCount) {
        console.log('🚫 消息数量未变化，跳过自动保存');
        return;
      }
      
      // 延迟保存，避免频繁保存
      const timer = setTimeout(() => {
        if (messages.length > 0) {
          // 只保存非loading消息，保存完整的Message对象
          const messagesToSave = messages
            .filter(msg => msg.type !== 'loading');
          
          if (messagesToSave.length > 0) {
            const currentSettings: ChatSettings = { useDeepThink, useMultiAgent };
            saveChat(chatId, messagesToSave, currentSettings);
            setLastSavedMessageCount(messagesToSave.length);
            console.log('💾 对话历史已自动保存:', chatId, messagesToSave.length, '条消息', '设置:', currentSettings);
          }
        }
      }, 1000);
      
      return () => clearTimeout(timer);
    }, [messages, isLoadingHistory, chatId, saveChat, useDeepThink, useMultiAgent, lastSavedMessageCount]);

  const handleSendMessage = async () => {
    if (!inputValue.trim() && !isLoading) return; // 如果不是中断且没有输入内容，直接返回

    // 如果正在加载，中断当前请求
    if (isLoading && currentAbortController) {
      console.log('🛑 中断当前对话');
      currentAbortController.abort();
      setCurrentAbortController(null);
      setIsLoading(false);
      
      // 将中断的消息标记为完成
      setMessages(prev => prev.map(msg => {
        if (msg.type === 'loading') {
          return {
            ...msg,
            type: 'assistant' as const,
            content: msg.content + '\n\n[对话已被用户中断]',
            displayContent: msg.displayContent + '\n\n[对话已被用户中断]',
            endTime: new Date()
          };
        }
        return msg;
      }));
      
      // 如果有新输入内容，继续发送新消息
      if (!inputValue.trim()) {
        return;
      }
    }

    // 创建新的AbortController
    const abortController = new AbortController();
    setCurrentAbortController(abortController);

    // 添加用户消息
    const userMessage = addUserMessage(inputValue.trim());
    
    // 添加loading消息
    const settings: ChatSettings = { useDeepThink, useMultiAgent };
    addLoadingMessage(settings);
    
    setInputValue('');
    setIsLoading(true);

    try {
      // 构建规则偏好和工作流context
      const enabledPreferences = state.rulePreferences.filter(pref => pref.enabled);
      const enabledWorkflows = state.workflowTemplates.filter(workflow => workflow.enabled);
      
      // 转换工作流格式以匹配后端期望的格式
      const availableWorkflows = enabledWorkflows.length > 0 ? 
        enabledWorkflows.reduce((acc, workflow) => {
          // 将嵌套对象格式的工作流步骤转换为字符串数组格式
          const convertStepsToArray = (stepsObj: { [key: string]: any }): string[] => {
            const stepArray: string[] = [];
            
            // 递归处理步骤，保持顺序
            const processStep = (step: any, level: number = 0): void => {
              const indent = '  '.repeat(level);
              stepArray.push(`${indent}${step.name}: ${step.description}`);
              
              // 如果有子步骤，递归处理
              if (step.substeps && Object.keys(step.substeps).length > 0) {
                Object.values(step.substeps).forEach((substep: any) => {
                  processStep(substep, level + 1);
                });
              }
            };
            
            // 按order排序并处理所有根步骤
            const rootSteps = Object.values(stepsObj).sort((a: any, b: any) => (a.order || 0) - (b.order || 0));
            rootSteps.forEach((step: any) => {
              processStep(step);
            });
            
            return stepArray;
          };
          
          const steps = convertStepsToArray(workflow.steps);
          acc[workflow.name] = steps;
          return acc;
        }, {} as Record<string, string[]>) : null;

      const systemContext: any = {};
      
      if (enabledPreferences.length > 0) {
        systemContext.rule_preferences = enabledPreferences.map(pref => ({
          name: pref.name,
          content: pref.content
        }));
      }
      
      if (availableWorkflows) {
        systemContext.available_workflows = availableWorkflows;
      }
      
      const finalSystemContext = Object.keys(systemContext).length > 0 ? systemContext : null;

      // 构建请求数据
      const requestData = {
        type: 'chat',
        messages: [...messages, userMessage].map(msg => {
          const messageData: any = {
          role: msg.role,
          content: msg.displayContent, // 使用displayContent而不是content
          message_id: msg.id,
          type: msg.type || 'normal'
          };
          
          // 如果消息包含工具调用，添加tool_calls字段
          if (msg.toolCalls && msg.toolCalls.length > 0) {
            messageData.tool_calls = msg.toolCalls.map(toolCall => ({
              id: toolCall.id,
              type: 'function',
              function: {
                name: toolCall.name,
                arguments: JSON.stringify(toolCall.arguments || {})
              }
            }));
          }
          
          return messageData;
        }),
        use_deepthink: useDeepThink,
        use_multi_agent: useMultiAgent,
        session_id: sessionId,
        system_context: finalSystemContext
      };

        console.log('🌐 发起Fetch请求:', '/api/chat-stream');
        const response = await fetch('/api/chat-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData),
        signal: abortController.signal, // 添加中断信号
      });

        console.log('📡 收到响应:', response.status, response.statusText);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

        console.log('📺 这是流式响应，不能在这里读取body');

      // 处理流式响应
      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('无法获取响应流');
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = new TextDecoder().decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const jsonStr = line.slice(6);
              // 跳过空行
              if (!jsonStr.trim()) continue;
              
              const data = JSON.parse(jsonStr);
                console.log('📦 收到数据:', data);
              
              switch (data.type) {
                case 'chat_chunk':
                  handleMessageChunk(data);
                  break;
                case 'json_chunk':
                  // 处理分块JSON
                  handleJsonChunk(data);
                  break;
                case 'complete_json':
                  // 处理完整JSON（小于32KB的数据）
                  console.log(`📦 [COMPLETE] 接收完整JSON: ${data.size} 字符`);
                  handleMessageChunk(data.data);
                  break;
                case 'chunk_start':
                  console.log(`🚀 [CHUNK START] 开始接收分块数据: ${data.total_chunks} 块, 总大小 ${data.total_size} 字符`);
                  break;
                case 'chunk_end':
                  console.log(`🏁 [CHUNK END] 分块传输结束: ${data.message_id}`);
                  break;
                case 'chat_complete':
                  setIsLoading(false);
                    console.log('✅ 对话完成');
                  saveChatHistory();
                  break;
                case 'error':
                  setIsLoading(false);
                    addErrorMessage(data.message);
                  break;
              }
            } catch (error) {
                console.error('❌ 解析JSON失败:', error);
                console.error('❌ 原始数据长度:', line.length);
                console.error('❌ 完整原始数据:', line);
                
                // 将原始数据保存到localStorage，方便调试
                const debugData = {
                  timestamp: new Date().toISOString(),
                  error: error instanceof Error ? error.message : String(error),
                  rawData: line,
                  dataLength: line.length
                };
                
                // 获取现有的调试数据
                const existingDebugData = localStorage.getItem('json_parse_errors');
                const debugArray = existingDebugData ? JSON.parse(existingDebugData) : [];
                debugArray.push(debugData);
                
                // 只保留最近的10条错误记录
                if (debugArray.length > 10) {
                  debugArray.splice(0, debugArray.length - 10);
                }
                
                localStorage.setItem('json_parse_errors', JSON.stringify(debugArray));
                console.error('❌ 调试数据已保存到localStorage，键名: json_parse_errors');
                console.error('💡 在控制台运行以下命令查看所有错误数据:');
                console.error('   JSON.parse(localStorage.getItem("json_parse_errors"))');
                console.error('💡 在控制台运行以下命令查看最新错误的原始数据:');
                console.error('   JSON.parse(localStorage.getItem("json_parse_errors")).pop().rawData');
                
                // 尝试修复JSON解析问题
                try {
                  const jsonStr = line.slice(6);
                  if (jsonStr.trim()) {
                    // 检查是否是分块JSON的一部分
                    if (line.includes('"type": "json_chunk"')) {
                      console.log('🔧 检测到可能的分块JSON数据，尝试部分解析');
                      
                      // 尝试从不完整的JSON中提取分块信息
                      const chunkIdMatch = jsonStr.match(/"chunk_id":\s*"([^"]+)"/);
                      const chunkIndexMatch = jsonStr.match(/"chunk_index":\s*(\d+)/);
                      const totalChunksMatch = jsonStr.match(/"total_chunks":\s*(\d+)/);
                      
                      if (chunkIdMatch && chunkIndexMatch && totalChunksMatch) {
                        console.log('🔧 检测到分块JSON信息，但数据不完整，等待更多数据');
                        continue; // 等待更多数据
                      }
                    }
                    
                    // 如果是工具调用相关的数据，尝试提取基本信息
                    if (line.includes('"role": "tool"') && line.includes('"content":')) {
                      console.log('🔧 检测到工具调用数据，尝试提取基本信息');
                      
                      // 使用正则表达式提取基本字段
                      const messageIdMatch = jsonStr.match(/"message_id":\s*"([^"]+)"/);
                      const roleMatch = jsonStr.match(/"role":\s*"([^"]+)"/);
                      const typeMatch = jsonStr.match(/"type":\s*"([^"]+)"/);
                      
                      if (messageIdMatch && roleMatch && typeMatch) {
                        const simpleToolMessage = {
                          type: typeMatch[1],
                          message_id: messageIdMatch[1],
                          role: roleMatch[1],
                          content: {},
                          show_content: '🔍 搜索完成，结果已获取',
                          step_type: 'tool_result'
                        };
                        
                        console.log('🔧 创建简化工具消息:', simpleToolMessage);
                        handleMessageChunk(simpleToolMessage);
                        continue; // 成功处理，跳过后续错误处理
                      }
                    }
                    
                    // 尝试其他类型的消息修复
                    const messageIdMatch = jsonStr.match(/"message_id":\s*"([^"]+)"/);
                    const typeMatch = jsonStr.match(/"type":\s*"([^"]+)"/);
                    const roleMatch = jsonStr.match(/"role":\s*"([^"]+)"/);
                    
                    if (messageIdMatch && typeMatch) {
                      console.log('🔧 尝试创建基本消息结构');
                      const basicMessage = {
                        type: typeMatch[1],
                        message_id: messageIdMatch[1],
                        role: roleMatch ? roleMatch[1] : 'assistant',
                        content: {},
                        show_content: '',
                        step_type: 'unknown'
                      };
                      
                      switch (basicMessage.type) {
                        case 'chat_chunk':
                          handleMessageChunk(basicMessage);
                          break;
                        case 'chat_complete':
                          setIsLoading(false);
                          console.log('✅ 对话完成');
                          saveChatHistory();
                          break;
                        case 'error':
                          setIsLoading(false);
                          addErrorMessage('处理消息时出现错误');
                          break;
                      }
                    }
                  }
                } catch (secondError) {
                  console.error('❌ 所有修复尝试都失败:', secondError);
                }
            }
          }
        }
      }

    } catch (error) {
      console.error('❌ 发送消息失败:', error);
      setIsLoading(false);
      setCurrentAbortController(null);
      
      // 检查是否是用户主动中断
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('✅ 用户主动中断对话');
        // 不显示错误消息，因为这是用户主动行为
        return;
      }
      
      addErrorMessage(`连接错误: ${error}`);
    } finally {
      // 确保清理AbortController
      setCurrentAbortController(null);
    }
  };

    const handleExampleClick = (example: string) => {
      setInputValue(example);
    };
    
    const handleToolCallClick = (toolCall: ToolCall) => {
      // 找到包含这个工具调用的消息，获取正确的时间戳
      const messageWithTool = messages.find(msg => 
        msg.toolCalls?.some(tc => tc.id === toolCall.id)
      );
      
      // 将ToolCall转换为ToolCallData格式
      const toolCallData: ToolCallData = {
        id: toolCall.id,
        toolName: toolCall.name,
        parameters: toolCall.arguments || {}, // 确保参数正确传递
        result: toolCall.result,
        duration: toolCall.duration,
        status: toolCall.status || 'running',
        error: toolCall.error,
        timestamp: messageWithTool?.timestamp || new Date() // 使用消息的时间戳
      };
      
      setSelectedToolCall(toolCallData);
      setToolPanelVisible(true);

      // 关闭文件查看器
      setFileViewerVisible(false);
      setSelectedFile(null);
    };

    const handleToolPanelClose = () => {
      setToolPanelVisible(false);
      setSelectedToolCall(null);
    };

    // 处理文件点击
    const handleFileClick = (fileUrl: string, fileName: string) => {
      setSelectedFile({ url: fileUrl, name: fileName });
      setFileViewerVisible(true);
      
      // 关闭工具面板
      setToolPanelVisible(false);
      setSelectedToolCall(null);
    };

    // 关闭文件查看器
    const handleFileViewerClose = () => {
      setFileViewerVisible(false);
      setSelectedFile(null);
    };

  const getLayoutWidths = () => {
    const isToolPanelOpen = toolPanelVisible && selectedToolCall;
    const isFileViewerOpen = fileViewerVisible && selectedFile;

    if (isToolPanelOpen) {
      return { main: '60%', panel: '40%' };
    }
    if (isFileViewerOpen) {
      return { main: '60%', panel: '40%' };
    }
    return { main: '100%', panel: '0%' };
  };

  const layout = getLayoutWidths();

  return (
    <div style={{ 
      height: '100vh', 
      display: 'flex', 
      flexDirection: 'row',
      overflow: 'hidden',
      background: '#f8fafc'
    }}>
      {/* 主聊天区域 */}
      <div style={{ 
        width: layout.main,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        transition: 'width 0.3s ease-in-out'
      }}>
        {/* 消息列表 */}
        <MessageList 
          messages={messages} 
          onExampleClick={handleExampleClick}
          onToolCallClick={handleToolCallClick}
          onFileClick={handleFileClick}
          settings={{ useDeepThink, useMultiAgent }}
        />

        {/* 输入区域 */}
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSendMessage}
          isLoading={isLoading}
          useDeepThink={useDeepThink}
          useMultiAgent={useMultiAgent}
          onDeepThinkChange={setUseDeepThink}
          onMultiAgentChange={setUseMultiAgent}
        />
      </div>
      
      {/* 右侧分屏容器 */}
      {layout.panel !== '0%' && (
        <div style={{ 
          width: layout.panel,
          flexShrink: 0,
          transition: 'width 0.3s ease-in-out',
          borderLeft: '1px solid #f0f0f0' 
        }}>
          {toolPanelVisible && (
            <ToolDetailPanel
              toolCall={selectedToolCall}
              onClose={handleToolPanelClose}
            />
          )}
          {fileViewerVisible && (
            <FileViewer
              fileUrl={selectedFile!.url}
              fileName={selectedFile!.name}
              onClose={handleFileViewerClose}
            />
          )}
        </div>
      )}
    </div>
  );
  }
  );

export default ChatInterface;