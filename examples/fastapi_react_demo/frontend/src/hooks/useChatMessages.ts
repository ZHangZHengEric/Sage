import { useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { Message, ChatSettings } from '../types/chat';

export const useChatMessages = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const getAgentType = (role: string): string => {
    const agentTypeMap: Record<string, string> = {
      'deepthink': '深度思考',
      'task_analyzer': '任务分析师',
      'code_agent': '代码智能体',
      'web_search_agent': '网络搜索智能体',
      'text_agent': '文本智能体',
      'assistant': 'Zavix',
      'tool': 'Zavix',
      'default': 'Zavix'
    };
    return agentTypeMap[role] || agentTypeMap['default'];
  };

  const addLoadingMessage = useCallback((settings: ChatSettings) => {
    // 根据设置显示不同的加载文字，移除点符号避免与动画点重复
    const loadingText = settings.useDeepThink || settings.useMultiAgent ? '🤔 正在思考' : '💬 正在回复';
    
    // 确保loading消息的时间戳晚于之前的消息
    const now = new Date();
    const loadingMessage: Message = {
      id: uuidv4(),
      role: 'assistant',
      content: '',
      displayContent: loadingText,
      timestamp: now,
      type: 'loading',
      startTime: now,
      endTime: now,
      duration: 0
    };
    
    setMessages(prev => {
      // 先移除现有的loading消息，避免重复
      const filtered = prev.filter(msg => msg.type !== 'loading');
      return [...filtered, loadingMessage];
    });
    return loadingMessage.id;
  }, []);

  const removeLoadingMessage = useCallback(() => {
    setMessages(prev => {
      const updated = [...prev];
      for (let i = updated.length - 1; i >= 0; i--) {
        if (updated[i].type === 'loading') {
          updated.splice(i, 1);
          break;
        }
      }
      return updated;
    });
  }, []);

  const addUserMessage = useCallback((content: string) => {
    const userMessage: Message = {
      id: uuidv4(),
      role: 'user',
      content,
      timestamp: new Date(),
      displayContent: content,
      startTime: new Date(),
      endTime: new Date(),
      duration: 0
    };
    setMessages(prev => [...prev, userMessage]);
    return userMessage;
  }, []);

  const handleMessageChunk = useCallback((data: any) => {
    if (data.message_id && (data.show_content !== undefined || data.tool_calls)) {
      const messageId = data.message_id;
      
      // 如果是tool角色，处理工具调用结果
      if (data.role === 'tool') {
        console.log('🔧 [TOOL MESSAGE] 处理工具消息:', {
          messageId,
          content: data.content,
          showContent: data.show_content,
          toolCalls: data.tool_calls
        });
        
        setMessages(prev => {
          const updated = [...prev];
          // 找到最近的assistant消息，更新其工具调用信息
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === 'assistant') {
              const existingMessage = updated[i];
              let updatedToolCalls = [...(existingMessage.toolCalls || [])];
              
              // 尝试从content中解析工具结果
              let toolResult = null;
              if (data.content) {
                try {
                  // 如果content是字符串且看起来像JSON，尝试解析
                  if (typeof data.content === 'string' && data.content.trim().startsWith('{')) {
                    toolResult = JSON.parse(data.content);
                  } else {
                    // 否则直接使用content
                    toolResult = data.content;
                  }
                  console.log('🔧 解析工具结果:', toolResult);
                } catch (e) {
                  console.warn('工具结果解析失败，使用原始内容:', e);
                  toolResult = { raw: data.content };
                }
              }
              
              // 如果有结构化的tool_calls数据，使用它
              if (data.tool_calls) {
                data.tool_calls.forEach((toolCall: any) => {
                  const existingToolIndex = updatedToolCalls.findIndex(tc => tc.id === toolCall.id);
                  if (existingToolIndex >= 0) {
                    updatedToolCalls[existingToolIndex] = {
                      ...updatedToolCalls[existingToolIndex],
                      ...toolCall,
                      result: toolResult,
                      status: 'success'
                    };
                  }
                });
              } else if (updatedToolCalls.length > 0) {
                // 如果没有结构化数据，但有工具调用，更新最后一个工具调用的结果
                const lastToolIndex = updatedToolCalls.length - 1;
                updatedToolCalls[lastToolIndex] = {
                  ...updatedToolCalls[lastToolIndex],
                  result: toolResult,
                  status: 'success'
                };
              }
              
              updated[i] = {
                ...existingMessage,
                toolCalls: updatedToolCalls
              };
              break;
            }
          }
          return updated;
        });
        
        // 重要：tool角色的消息不创建新气泡，直接返回
        return;
      }
      
      let showContent = data.show_content || '';
      
      // // 智能回退：如果show_content为空但来自专业智能体，显示友好提示
      // if (!showContent && data.agent_type && 
      //     (data.agent_type === 'code_agent' || 
      //      data.agent_type === 'task_analyzer' ||
      //      data.step_type === 'do_subtask' ||
      //      data.step_type === 'task_analysis_result')) {
      //   showContent = `🤖 ${getAgentType(data.agent_type)}正在处理中...`;
      // }
      
      // 绝对不直接使用content字段，只使用处理后的show_content
      
      setMessages(prev => {
        const existingIndex = prev.findIndex(m => m.id === messageId);
        const now = new Date();
        
        if (existingIndex >= 0) {
          // 更新现有消息 - 同一个message_id的内容应该累加
          const updated = [...prev];
          const existingMessage = updated[existingIndex];
          
          // 处理工具调用更新
          let updatedToolCalls = existingMessage.toolCalls || [];
          if (data.tool_calls) {
            data.tool_calls.forEach((toolCall: any) => {
              const existingToolIndex = updatedToolCalls.findIndex(tc => tc.id === toolCall.id);
              if (existingToolIndex >= 0) {
                // 更新现有工具调用
                updatedToolCalls[existingToolIndex] = {
                  ...updatedToolCalls[existingToolIndex],
                  ...toolCall,
                  status: toolCall.status || updatedToolCalls[existingToolIndex].status
                };
              } else {
                // 添加新工具调用
                updatedToolCalls.push({
                  id: toolCall.id,
                  name: toolCall.name,
                  arguments: toolCall.arguments || {},
                  result: toolCall.result,
                  status: toolCall.status || 'running',
                  error: toolCall.error,
                  duration: toolCall.duration
                });
              }
            });
          }
          
          updated[existingIndex] = {
            ...existingMessage,
            content: existingMessage.displayContent + showContent,
            displayContent: existingMessage.displayContent + showContent,
            timestamp: now,
            endTime: now,
            duration: existingMessage.startTime ? now.getTime() - existingMessage.startTime.getTime() : 0,
            toolCalls: updatedToolCalls
          };
          return updated;
        } else {
          // 创建新消息时，如果有实际显示内容，则移除loading消息
          const shouldRemoveLoading = showContent.trim() !== '' || data.tool_calls;
          let updated = [...prev];
          
          if (shouldRemoveLoading) {
            // 移除最后一个loading消息
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].type === 'loading') {
                updated.splice(i, 1);
                break;
              }
            }
          }
          
          // 只有当有显示内容或工具调用时才创建消息
          if (showContent.trim() !== '' || data.tool_calls) {
            // 处理工具调用
            let toolCalls = [];
            if (data.tool_calls) {
              // 优先使用后端返回的结构化工具调用数据
              toolCalls = data.tool_calls.map((toolCall: any) => ({
                id: toolCall.id,
                name: toolCall.name,
                arguments: toolCall.arguments || {},
                result: toolCall.result,
                status: toolCall.status || 'running',
                error: toolCall.error,
                duration: toolCall.duration
              }));
            } else if (showContent.includes('调用工具：')) {
              // 只有在没有结构化数据时才从文本中提取
              const toolNameMatch = showContent.match(/调用工具：(\w+)/);
              if (toolNameMatch) {
                const toolName = toolNameMatch[1];
                // 尝试从文本中提取参数
                const paramsMatch = showContent.match(/参数\*\*:\s*\n([\s\S]*?)(?=\n\n|$)/);
                let extractedArgs: Record<string, any> = {};
                if (paramsMatch) {
                  try {
                    // 简单的参数解析
                    const paramLines = paramsMatch[1].split('\n');
                    paramLines.forEach((line: string) => {
                      const match = line.match(/- \*\*(\w+)\*\*:\s*"([^"]+)"/);
                      if (match) {
                        extractedArgs[match[1]] = match[2];
                      }
                    });
                  } catch (e) {
                    console.warn('Failed to parse tool arguments from text:', e);
                  }
                }
                
                toolCalls.push({
                  id: `tool_${Date.now()}`,
                  name: toolName,
                  arguments: extractedArgs,
                  status: 'running'
                });
              }
            }
            
            const newMessage: Message = {
              id: messageId,
              role: (data.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant' | 'system',
              content: showContent,
              displayContent: showContent,
              timestamp: now,
              type: data.step_type,
              agentType: getAgentType(data.agent_type || data.role || 'assistant'),
              startTime: now,
              endTime: now,
              duration: 0,
              toolCalls: toolCalls.length > 0 ? toolCalls : undefined
            };
            updated.push(newMessage);
          }
          
          return updated;
        }
      });
    }
  }, []);

  const addErrorMessage = useCallback((error: string) => {
    const errorMessage: Message = {
      id: uuidv4(),
      role: 'system',
      content: `错误: ${error}`,
      displayContent: `错误: ${error}`,
      timestamp: new Date(),
      type: 'error'
    };
    setMessages(prev => [...prev, errorMessage]);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  return {
    messages,
    isLoading,
    setIsLoading,
    addLoadingMessage,
    removeLoadingMessage,
    addUserMessage,
    handleMessageChunk,
    addErrorMessage,
    clearMessages,
    setMessages
  };
}; 