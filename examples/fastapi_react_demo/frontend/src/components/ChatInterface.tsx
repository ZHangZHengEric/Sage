import React, { useState, useEffect, useRef, forwardRef, useImperativeHandle } from 'react';
import { 
  Card, 
  Input, 
  Button, 
  List, 
  Avatar, 
  Space, 
  Switch, 
  Spin,
  Alert,
  Tag,
  Divider,
  Collapse
} from 'antd';
import { 
  SendOutlined, 
  UserOutlined, 
  RobotOutlined, 
  ClearOutlined,
  BranchesOutlined,
  ThunderboltOutlined,
  DownOutlined,
  UpOutlined
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { v4 as uuidv4 } from 'uuid';
import { useSystem } from '../context/SystemContext';
import { useChatHistory, ChatHistoryItem } from '../hooks/useChatHistory';

const { TextArea } = Input;
const { Panel } = Collapse;

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string; // 真正的消息内容，用于后续对话
  displayContent: string; // 显示内容（来自show_content）
  timestamp: Date;
  type?: string;
  agentType?: string;
  startTime?: Date; // 消息开始时间
  endTime?: Date; // 消息结束时间
  duration?: number; // 耗时（毫秒）
}

interface MessageGroup {
  userMessage: Message;
  deepThinkMessages: Message[];
  finalAnswer?: Message | Message[]; // 支持单个或多个最终答案
}

interface ChatInterfaceProps {
  currentChatId?: string;
  loadedMessages?: ChatHistoryItem['messages'] | null;
}

export interface ChatInterfaceRef {
  startNewChat: () => void;
  loadChat: (messages: ChatHistoryItem['messages']) => void;
}

const ChatInterface = forwardRef<ChatInterfaceRef, ChatInterfaceProps>(
  ({ currentChatId, loadedMessages }, ref) => {
  const { state } = useSystem();
  const { saveChat } = useChatHistory();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [useDeepThink, setUseDeepThink] = useState(true);
  const [useMultiAgent, setUseMultiAgent] = useState(true);
  const [sessionId, setSessionId] = useState(() => uuidv4());
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<any>(null);

  // 暴露给父组件的方法
  useImperativeHandle(ref, () => ({
    startNewChat: () => {
      console.log('ChatInterface - startNewChat方法被调用');
      console.log('ChatInterface - 当前消息数量:', messages.length);
      setMessages([]);
      console.log('ChatInterface - 消息已清空');
      setSessionId(uuidv4());
      console.log('ChatInterface - 新的sessionId已生成');
      setInputValue('');
      console.log('ChatInterface - 输入框已清空');
      setIsLoading(false);
      console.log('ChatInterface - loading状态已重置');
    },
    loadChat: (chatMessages: ChatHistoryItem['messages']) => {
      setMessages(chatMessages.map(msg => ({
        ...msg,
        timestamp: new Date(msg.timestamp)
      })));
      setInputValue('');
      setIsLoading(false);
    }
  }));

  // 当加载的消息改变时，更新当前消息
  useEffect(() => {
    if (loadedMessages) {
      setMessages(loadedMessages.map(msg => ({
        ...msg,
        timestamp: new Date(msg.timestamp)
      })));
    }
  }, [loadedMessages]);

  // 自动滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 保存对话到历史记录
  const saveCurrentChat = () => {
    if (messages.length > 0) {
      const chatId = currentChatId || sessionId;
      saveChat(chatId, messages);
    }
  };

  // 在每次消息更新后保存对话
  useEffect(() => {
    if (messages.length > 0 && !isLoading) {
      // 延迟保存，避免频繁更新
      const timer = setTimeout(() => {
        saveCurrentChat();
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [messages, isLoading, currentChatId, sessionId]);

  // 消息分组逻辑
  const groupMessages = (messages: Message[]): MessageGroup[] => {
    const groups: MessageGroup[] = [];
    let currentGroup: MessageGroup | null = null;

    console.log('开始分组消息:', {
      总消息数: messages.length,
      深度思考开启: useDeepThink,
      多智能体协作开启: useMultiAgent,
      消息列表: messages.map(m => ({
        id: m.id,
        role: m.role,
        type: m.type,
        agentType: m.agentType
      }))
    });

    for (const message of messages) {
      if (message.role === 'user') {
        // 如果之前有未完成的组，先推入
        if (currentGroup) {
          groups.push(currentGroup);
        }
        // 开始新的组
        currentGroup = {
          userMessage: message,
          deepThinkMessages: [],
          finalAnswer: undefined
        };
      } else if (message.role === 'assistant' && currentGroup) {
        // 根据配置决定消息分类
        if (useMultiAgent) {
          // 多智能体协作开启：除了 final_answer 都放入深度思考
          if (message.type === 'final_answer') {
            console.log('分类为最终答案 (多智能体模式):', message.type);
            currentGroup.finalAnswer = message;
          } else {
            console.log('分类为深度思考 (多智能体模式):', message.type);
            currentGroup.deepThinkMessages.push(message);
          }
        } else if (useDeepThink) {
          // 只有深度思考开启：只有 task_analysis_result 放入深度思考
          if (message.type === 'task_analysis_result') {
            console.log('分类为深度思考 (仅深度思考模式):', message.type);
            currentGroup.deepThinkMessages.push(message);
          } else {
            console.log('分类为最终答案 (仅深度思考模式):', message.type);
            // 如果已经有最终答案，将其转换为数组处理多个消息
            if (currentGroup.finalAnswer) {
              if (!Array.isArray(currentGroup.finalAnswer)) {
                currentGroup.finalAnswer = [currentGroup.finalAnswer];
              }
              currentGroup.finalAnswer.push(message);
            } else {
              currentGroup.finalAnswer = message;
            }
          }
        } else {
          // 都关闭：所有消息都放入常规显示
          console.log('分类为最终答案 (都关闭):', message.type);
          // 如果已经有最终答案，将其转换为数组处理多个消息
          if (currentGroup.finalAnswer) {
            if (!Array.isArray(currentGroup.finalAnswer)) {
              currentGroup.finalAnswer = [currentGroup.finalAnswer];
            }
            currentGroup.finalAnswer.push(message);
          } else {
            currentGroup.finalAnswer = message;
          }
        }
      }
    }

    // 推入最后一个组
    if (currentGroup) {
      groups.push(currentGroup);
    }

    console.log('消息分组完成:', {
      分组数量: groups.length,
      分组详情: groups.map((g, i) => ({
        组索引: i,
        用户消息: g.userMessage.displayContent.substring(0, 50),
        深度思考消息数: g.deepThinkMessages.length,
        深度思考消息类型: g.deepThinkMessages.map(m => m.type),
        最终答案: g.finalAnswer 
          ? Array.isArray(g.finalAnswer) 
            ? `${g.finalAnswer.length}个消息` 
            : g.finalAnswer.displayContent.substring(0, 50)
          : '无'
      }))
    });

    return groups;
  };

  // 获取智能体类型
  const getAgentType = (role: string): string => {
    if (role.includes('analysis')) return '分析智能体';
    if (role.includes('planning')) return '规划智能体';
    if (role.includes('executor')) return '执行智能体';
    if (role.includes('observation')) return '观察智能体';
    if (role.includes('summary')) return '总结智能体';
    if (role.includes('decompose')) return '分解智能体';
    return '智能体';
  };

  // 格式化耗时
  const formatDuration = (duration: number): string => {
    if (duration < 1000) {
      return `${Math.round(duration)}ms`;
    } else if (duration < 60000) {
      return `${(duration / 1000).toFixed(1)}s`;
    } else {
      const minutes = Math.floor(duration / 60000);
      const seconds = Math.floor((duration % 60000) / 1000);
      return `${minutes}m${seconds}s`;
    }
  };

  // 计算深度思考总耗时
  const calculateDeepThinkTotalDuration = (deepThinkMessages: Message[]): number => {
    return deepThinkMessages.reduce((total, msg) => total + (msg.duration || 0), 0);
  };

  // 渲染深度思考气泡框
  const renderDeepThinkBubble = (deepThinkMessages: Message[]) => {
    if (!deepThinkMessages.length) return null;

    // 获取智能体类型（取第一个消息的agentType）
    const agentType = deepThinkMessages[0]?.agentType;
    const totalDuration = calculateDeepThinkTotalDuration(deepThinkMessages);

    return (
      <div style={{
        marginBottom: '16px',
        display: 'flex',
        justifyContent: 'flex-start'
      }}>
        <div style={{ 
          maxWidth: '75%', 
          minWidth: '300px',
          width: '100%'
        }}>
          {/* 智能体类型标签 - 移到外面 */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '6px'
          }}>
            {agentType && (
              <div style={{
                fontSize: '12px',
                color: '#8b5cf6',
                fontWeight: 500
              }}>
                {agentType}
              </div>
            )}
            {totalDuration > 0 && (
              <div style={{
                fontSize: '11px',
                color: '#9ca3af',
                background: '#f8fafc',
                padding: '2px 6px',
                borderRadius: '4px',
                border: '1px solid #f1f5f9'
              }}>
                总耗时 {formatDuration(totalDuration)}
              </div>
            )}
          </div>

          {/* 可折叠的深度思考内容 */}
          <Collapse 
            ghost
            size="small"
            className="deep-think-collapse"
            style={{
              background: '#f8fafc',
              borderRadius: '12px',
              border: '1px solid #e2e8f0',
              boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)'
            }}
            expandIcon={({ isActive }) => (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '13px',
                color: '#6b7280',
                fontWeight: 500,
                padding: '4px 8px',
                borderRadius: '6px',
                background: isActive ? '#e0e7ff' : '#f3f4f6',
                border: '1px solid',
                borderColor: isActive ? '#c7d2fe' : '#e5e7eb',
                transition: 'all 0.2s ease'
              }}>
                {isActive ? <UpOutlined style={{ fontSize: '11px' }} /> : <DownOutlined style={{ fontSize: '11px' }} />}
                <span>{isActive ? '收起' : '展开'}</span>
              </div>
            )}
          >
            <Panel 
              header={
                <div style={{
                  fontSize: '14px',
                  color: '#374151',
                  fontWeight: 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <div style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: '#8b5cf6',
                    animation: 'deepThinkPulse 2s infinite'
                  }} />
                  深度思考过程
                </div>
              }
              key="1"
              style={{
                border: 'none',
                borderRadius: '12px'
              }}
            >
              <div 
                className="deep-think-content"
                style={{ 
                  maxHeight: '300px', 
                  overflowY: 'auto',
                  overflowX: 'hidden',
                  padding: '4px 0',
                  scrollbarWidth: 'thin',
                  scrollbarColor: '#cbd5e1 transparent',
                  wordWrap: 'break-word',
                  wordBreak: 'break-word'
                }}
              >
                {deepThinkMessages.map((message, index) => (
                  <div 
                    key={message.id} 
                    className="message-bubble"
                    style={{
                      marginBottom: index < deepThinkMessages.length - 1 ? '8px' : '0',
                      padding: '8px 12px',
                      background: '#ffffff',
                      borderRadius: '8px',
                      border: '1px solid #f1f5f9',
                      fontSize: '13px',
                      lineHeight: '1.5',
                      wordWrap: 'break-word',
                      wordBreak: 'break-word',
                      overflowWrap: 'break-word',
                      width: '100%',
                      boxSizing: 'border-box',
                      position: 'relative'
                    }}
                  >
                    {/* 单个消息的耗时显示 */}
                    {message.duration && message.duration > 0 && (
                      <div style={{
                        position: 'absolute',
                        top: '4px',
                        right: '8px',
                        fontSize: '10px',
                        color: '#9ca3af',
                        background: 'rgba(255, 255, 255, 0.9)',
                        padding: '1px 4px',
                        borderRadius: '3px',
                        border: '1px solid #f1f5f9'
                      }}>
                        {formatDuration(message.duration)}
                      </div>
                    )}
                    
                    <ReactMarkdown
                      components={{
                        p: ({children}) => (
                          <div style={{ 
                            margin: '2px 0', 
                            fontSize: '13px', 
                            lineHeight: '1.5',
                            color: '#374151'
                          }}>
                            {children}
                          </div>
                        ),
                        code: ({children}) => (
                          <code style={{
                            background: '#f1f5f9',
                            color: '#4338ca',
                            padding: '1px 4px',
                            borderRadius: '3px',
                            fontSize: '12px',
                            fontFamily: 'SF Mono, Monaco, Consolas, monospace',
                            wordBreak: 'break-all',
                            overflowWrap: 'break-word'
                          }}>
                            {children}
                          </code>
                        ),
                        ul: ({children}) => (
                          <ul style={{ 
                            margin: '4px 0', 
                            paddingLeft: '14px',
                            fontSize: '13px',
                            lineHeight: '1.5'
                          }}>
                            {children}
                          </ul>
                        ),
                        li: ({children}) => (
                          <li style={{ marginBottom: '1px' }}>
                            {children}
                          </li>
                        )
                      }}
                    >
                      {message.displayContent}
                    </ReactMarkdown>
                  </div>
                ))}
              </div>
            </Panel>
          </Collapse>
        </div>
      </div>
    );
  };

  // 处理消息块
  const handleMessageChunk = (data: any) => {
    if (data.message_id && (data.show_content !== undefined || data.content !== undefined)) {
      const messageId = data.message_id;
      const showContent = data.show_content || '';
      const realContent = data.content || '';
      
      console.log('处理消息块:', {
        message_id: messageId,
        show_content: showContent,
        content: realContent,
        step_type: data.step_type,
        agent_type: data.agent_type
      });

      setMessages(prev => {
        const existingIndex = prev.findIndex(m => m.id === messageId);
        const now = new Date();
        
        if (existingIndex >= 0) {
          // 更新现有消息
          const updated = [...prev];
          const existingMessage = updated[existingIndex];
          const updatedContent = existingMessage.content + realContent;
          const updatedDisplayContent = existingMessage.displayContent + showContent;
          
          updated[existingIndex] = {
            ...existingMessage,
            content: updatedContent,
            displayContent: updatedDisplayContent,
            timestamp: now,
            endTime: now,
            duration: existingMessage.startTime ? now.getTime() - existingMessage.startTime.getTime() : 0
          };
          return updated;
        } else {
          // 创建新消息
          const newMessage: Message = {
            id: messageId,
            role: (data.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant' | 'system',
            content: realContent,
            displayContent: showContent,
            timestamp: now,
            type: data.step_type,
            agentType: getAgentType(data.agent_type || data.role || 'assistant'),
            startTime: now,
            endTime: now,
            duration: 0
          };
          return [...prev, newMessage];
        }
      });
    }
  };

  // 发送消息
  const handleSendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: Message = {
      id: uuidv4(),
      role: 'user',
      content: inputValue,
      timestamp: new Date(),
      displayContent: inputValue,
      startTime: new Date(),
      endTime: new Date(),
      duration: 0
    };

    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);
    setInputValue('');

    try {
      // 构建请求数据
      const requestData = {
        type: 'chat',
        messages: [...messages, userMessage].map(msg => ({
          role: msg.role,
          content: msg.content,
          message_id: msg.id,
          type: msg.type || 'normal'
        })),
        use_deepthink: useDeepThink,
        use_multi_agent: useMultiAgent
      };

      console.log('发送请求参数:', {
        use_deepthink: useDeepThink,
        use_multi_agent: useMultiAgent,
        消息数量: requestData.messages.length
      });

      // 发送流式请求
      const response = await fetch('/api/chat-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

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
              const data = JSON.parse(line.slice(6));
              console.log('收到流式数据:', data);
              
              switch (data.type) {
                case 'chat_chunk':
                  handleMessageChunk(data);
                  break;
                case 'chat_complete':
                  setIsLoading(false);
                  console.log('聊天完成');
                  break;
                case 'error':
                  setIsLoading(false);
                  setMessages(prev => [...prev, {
                    id: uuidv4(),
                    role: 'system',
                    content: `错误: ${data.message}`,
                    displayContent: `错误: ${data.message}`,
                    timestamp: new Date(),
                    type: 'error'
                  }]);
                  break;
              }
            } catch (error) {
              console.error('解析JSON失败:', error, line);
            }
          }
        }
      }

    } catch (error) {
      console.error('发送消息失败:', error);
      setIsLoading(false);
      setMessages(prev => [...prev, {
        id: uuidv4(),
        role: 'system',
        content: `连接错误: ${error}`,
        displayContent: `连接错误: ${error}`,
        timestamp: new Date(),
        type: 'error'
      }]);
    }
  };

  // 清空对话
  const handleClearChat = () => {
    setMessages([]);
  };

  // 渲染消息 - 豆包风格
  const renderMessage = (message: Message) => {
    console.log('渲染单个消息:', {
      id: message.id,
      role: message.role,
      displayContent: message.displayContent,
      displayContentLength: message.displayContent.length
    });
    
    const isUser = message.role === 'user';
    const isError = message.type === 'error';
    
    return (
      <div
        key={message.id}
        className="message-bubble"
        style={{
          display: 'flex',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
          marginBottom: '12px'
        }}
      >
        <div style={{
          maxWidth: '75%',
          minWidth: '120px',
          position: 'relative'
        }}>
          {/* 智能体类型标签 */}
          {!isUser && message.agentType && (
            <div style={{
              fontSize: '12px',
              color: '#8b5cf6',
              marginBottom: '4px',
              fontWeight: 500
            }}>
              {message.agentType}
            </div>
          )}
          
          {/* 消息气泡 */}
          <div
            style={{
              background: isUser 
                ? '#6366f1' 
                : isError 
                  ? '#fef2f2' 
                  : '#ffffff',
              color: isUser 
                ? '#ffffff' 
                : isError 
                  ? '#dc2626' 
                  : '#1f2937',
              padding: '10px 14px',
              borderRadius: isUser 
                ? '16px 16px 4px 16px' 
                : '16px 16px 16px 4px',
              boxShadow: isUser 
                ? '0 1px 3px rgba(99, 102, 241, 0.3)'
                : '0 1px 3px rgba(0, 0, 0, 0.1)',
              border: isUser 
                ? 'none'
                : '1px solid #f1f5f9',
              fontSize: '14px',
              lineHeight: '1.5',
              wordBreak: 'break-word',
              position: 'relative'
            }}
          >
            {/* 消息耗时显示 */}
            {!isUser && message.duration && message.duration > 0 && (
              <div style={{
                position: 'absolute',
                top: '4px',
                right: '8px',
                fontSize: '10px',
                color: '#9ca3af',
                background: 'rgba(255, 255, 255, 0.9)',
                padding: '1px 4px',
                borderRadius: '3px',
                border: '1px solid #f1f5f9'
              }}>
                {formatDuration(message.duration)}
              </div>
            )}

            <ReactMarkdown
              components={{
                code({node, className, children, ...props}) {
                  const match = /language-(\w+)/.exec(className || '');
                  const isInline = !match;
                  
                  if (isInline) {
                    return (
                      <code 
                        style={{
                          background: isUser 
                            ? 'rgba(255, 255, 255, 0.2)' 
                            : '#f8fafc',
                          color: isUser 
                            ? '#ffffff' 
                            : '#475569',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          fontSize: '13px',
                          fontFamily: 'SF Mono, Monaco, Consolas, monospace'
                        }}
                      >
                        {children}
                      </code>
                    );
                  }
                  
                  return (
                    <SyntaxHighlighter
                      style={tomorrow as any}
                      language={match[1]}
                      PreTag="div"
                      customStyle={{
                        background: '#1e293b',
                        borderRadius: '8px',
                        fontSize: '12px',
                        margin: '8px 0',
                        boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)'
                      }}
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  );
                },
                p({children}) {
                  return <div style={{ margin: '4px 0' }}>{children}</div>;
                },
                ul({children}) {
                  return (
                    <ul style={{ 
                      margin: '8px 0', 
                      paddingLeft: '20px',
                      lineHeight: '1.5'
                    }}>
                      {children}
                    </ul>
                  );
                },
                ol({children}) {
                  return (
                    <ol style={{ 
                      margin: '8px 0', 
                      paddingLeft: '20px',
                      lineHeight: '1.5'
                    }}>
                      {children}
                    </ol>
                  );
                },
                blockquote({children}) {
                  return (
                    <blockquote style={{
                      borderLeft: `3px solid ${isUser ? 'rgba(255,255,255,0.3)' : '#e2e8f0'}`,
                      margin: '8px 0',
                      fontStyle: 'italic',
                      opacity: 0.9,
                      background: isUser 
                        ? 'rgba(255, 255, 255, 0.1)' 
                        : '#f8fafc',
                      borderRadius: '6px',
                      padding: '8px 8px 8px 12px'
                    }}>
                      {children}
                    </blockquote>
                  );
                }
              }}
            >
              {message.displayContent}
            </ReactMarkdown>
          </div>
          
          {/* 时间戳 */}
          <div style={{ 
            fontSize: '11px', 
            color: '#9ca3af',
            marginTop: '4px',
            textAlign: isUser ? 'right' : 'left'
          }}>
            {message.timestamp.toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit'
            })}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div style={{ 
      height: '100vh', 
      display: 'flex', 
      flexDirection: 'column',
      overflow: 'hidden',
      background: '#f8fafc'
    }}>
      {/* 消息列表 - 豆包风格 */}
      <div style={{ 
        flex: 1, 
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center'
      }}>
        <div style={{
          width: '100%',
          maxWidth: '768px',
          padding: '16px 24px'
        }}>
          {messages.length === 0 ? (
            <div style={{ 
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
              textAlign: 'center',
              color: '#6b7280',
              padding: '60px 20px',
              minHeight: '400px'
            }}>
              <div style={{
                width: '64px',
                height: '64px',
                borderRadius: '16px',
                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '20px',
                boxShadow: '0 4px 12px rgba(99, 102, 241, 0.2)'
              }}>
                <RobotOutlined style={{ fontSize: '28px', color: '#ffffff' }} />
              </div>
              
              <div style={{ fontSize: '18px', fontWeight: 600, marginBottom: '8px', color: '#1f2937' }}>
                您好，我是 Sage 助手
              </div>
              <div style={{ fontSize: '14px', lineHeight: '1.5', marginBottom: '24px', maxWidth: '320px' }}>
                我是您的多智能体协作助手，可以运用深度思考为您解决各种复杂问题。
              </div>
              
              {/* 功能特色 */}
              <div style={{ 
                display: 'flex', 
                gap: '12px',
                flexWrap: 'wrap',
                justifyContent: 'center',
                marginBottom: '32px'
              }}>
                <div style={{
                  padding: '12px 16px',
                  background: '#ffffff',
                  borderRadius: '8px',
                  border: '1px solid #f1f5f9',
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <ThunderboltOutlined style={{ fontSize: '16px', color: '#f59e0b' }} />
                  <span style={{ fontSize: '13px', fontWeight: 500, color: '#374151' }}>
                    深度思考
                  </span>
                </div>
                
                <div style={{
                  padding: '12px 16px',
                  background: '#ffffff',
                  borderRadius: '8px',
                  border: '1px solid #f1f5f9',
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <BranchesOutlined style={{ fontSize: '16px', color: '#10b981' }} />
                  <span style={{ fontSize: '13px', fontWeight: 500, color: '#374151' }}>
                    多智能体协作
                  </span>
                </div>
              </div>

              {/* 使用示例 */}
              <div style={{ 
                width: '100%',
                maxWidth: '600px'
              }}>
                <div style={{ 
                  fontSize: '16px', 
                  fontWeight: 600, 
                  color: '#1f2937', 
                  marginBottom: '16px' 
                }}>
                  试试这些示例
                </div>
                
                <div style={{ 
                  display: 'grid', 
                  gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', 
                  gap: '12px'
                }}>
                  {[
                    {
                      title: "数学计算",
                      example: "计算 45 乘以 76 再减去 4 的结果",
                      icon: "🔢"
                    },
                    {
                      title: "代码编程", 
                      example: "用 Python 写一个快速排序算法",
                      icon: "💻"
                    },
                    {
                      title: "文档写作",
                      example: "帮我写一份项目总结报告的大纲",
                      icon: "📝"
                    },
                    {
                      title: "数据分析",
                      example: "分析这组销售数据的趋势和特点",
                      icon: "📊"
                    }
                  ].map((item, index) => (
                    <div
                      key={index}
                      style={{
                        padding: '16px',
                        background: '#ffffff',
                        borderRadius: '12px',
                        border: '1px solid #f1f5f9',
                        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        textAlign: 'left'
                      }}
                      onClick={() => setInputValue(item.example)}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = '#e0e7ff';
                        e.currentTarget.style.boxShadow = '0 4px 12px rgba(99, 102, 241, 0.1)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = '#f1f5f9';
                        e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.05)';
                      }}
                    >
                      <div style={{ 
                        display: 'flex', 
                        alignItems: 'center', 
                        gap: '8px', 
                        marginBottom: '8px' 
                      }}>
                        <span style={{ fontSize: '18px' }}>{item.icon}</span>
                        <span style={{ 
                          fontSize: '14px', 
                          fontWeight: 600, 
                          color: '#1f2937' 
                        }}>
                          {item.title}
                        </span>
                      </div>
                      <div style={{ 
                        fontSize: '13px', 
                        color: '#6b7280', 
                        lineHeight: '1.4' 
                      }}>
                        {item.example}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {(() => {
                console.log('渲染消息列表:', {
                  总消息数: messages.length,
                  消息列表: messages.map(m => ({
                    id: m.id,
                    role: m.role,
                    displayContent长度: m.displayContent.length,
                    displayContent前50字符: m.displayContent.substring(0, 50),
                    是否有内容: m.displayContent.trim().length > 0
                  }))
                });
                
                const filteredMessages = messages.filter(msg => msg.displayContent.trim().length > 0);
                console.log('过滤后消息数:', filteredMessages.length);
                
                // 使用分组逻辑渲染消息
                const messageGroups = groupMessages(filteredMessages);
                console.log('消息分组:', messageGroups);
                
                return messageGroups.map((group, groupIndex) => (
                  <div key={`group-${groupIndex}`} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {/* 渲染用户消息 */}
                    {renderMessage(group.userMessage)}
                    
                    {/* 渲染深度思考气泡框 */}
                    {renderDeepThinkBubble(group.deepThinkMessages)}
                    
                    {/* 渲染最终答案 */}
                    {group.finalAnswer && (
                      Array.isArray(group.finalAnswer) 
                        ? group.finalAnswer.map((msg, index) => renderMessage(msg))
                        : renderMessage(group.finalAnswer)
                    )}
                  </div>
                ));
              })()}
            </div>
          )}
          
          {isLoading && (
            <div style={{ 
              display: 'flex', 
              justifyContent: 'center', 
              padding: '20px 0',
              alignItems: 'center',
              gap: '8px',
              color: '#6b7280'
            }}>
              <Spin size="small" />
              <span>智能体正在思考...</span>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* 豆包风格的输入区域 */}
      <div style={{ 
        padding: '16px 24px 20px',
        background: '#f8fafc',
        flexShrink: 0
      }}>
        {/* 输入框容器 - 豆包风格多行设计 */}
        <div style={{
          maxWidth: '768px',
          margin: '0 auto'
        }}>
          <div 
            className="chat-input-container"
            style={{
              position: 'relative',
              borderRadius: '16px',
              background: '#ffffff',
              transition: 'all 0.2s ease',
              minHeight: '140px',
              display: 'flex',
              flexDirection: 'column',
              border: '1px solid #f1f5f9'
            }}
          >
            {/* 顶部功能开关行 */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '12px 16px 8px 16px',
              borderBottom: '1px solid #f8fafc'
            }}>
              <div style={{
                display: 'flex',
                gap: '12px',
                fontSize: '12px'
              }}>
                <label style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '6px',
                  color: '#6b7280',
                  cursor: 'pointer',
                  padding: '4px 8px',
                  borderRadius: '12px',
                  background: useDeepThink ? '#f0f9ff' : 'transparent',
                  border: useDeepThink ? '1px solid #bae6fd' : '1px solid transparent',
                  transition: 'all 0.2s',
                  fontSize: '12px'
                }}>
                  <Switch 
                    checked={useDeepThink} 
                    onChange={setUseDeepThink}
                    size="small"
                  />
                  <ThunderboltOutlined style={{ color: useDeepThink ? '#0ea5e9' : '#6b7280', fontSize: '12px' }} />
                  深度思考
                </label>
                
                <label style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '6px',
                  color: '#6b7280',
                  cursor: 'pointer',
                  padding: '4px 8px',
                  borderRadius: '12px',
                  background: useMultiAgent ? '#f0fdf4' : 'transparent',
                  border: useMultiAgent ? '1px solid #bbf7d0' : '1px solid transparent',
                  transition: 'all 0.2s',
                  fontSize: '12px'
                }}>
                  <Switch 
                    checked={useMultiAgent} 
                    onChange={setUseMultiAgent}
                    size="small"
                  />
                  <BranchesOutlined style={{ color: useMultiAgent ? '#10b981' : '#6b7280', fontSize: '12px' }} />
                  智能体协作
                </label>
              </div>

              {/* 右侧附加功能按钮 */}
              <div style={{
                display: 'flex',
                gap: '8px',
                alignItems: 'center'
              }}>
                <Button
                  type="text"
                  size="small"
                  style={{
                    color: '#9ca3af',
                    fontSize: '12px',
                    height: '24px',
                    padding: '0 8px',
                    borderRadius: '6px'
                  }}
                >
                  @ 技能
                </Button>
                <Button
                  type="text"
                  size="small"
                  style={{
                    color: '#9ca3af',
                    fontSize: '12px',
                    height: '24px',
                    padding: '0 8px',
                    borderRadius: '6px'
                  }}
                >
                  / 文件
                </Button>
              </div>
            </div>

            {/* 输入框和发送按钮区域 */}
            <div style={{
              display: 'flex',
              alignItems: 'flex-end',
              padding: '8px 16px 12px 16px',
              gap: '12px'
            }}>
              <div style={{ flex: 1, position: 'relative' }}>
                <TextArea
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder="发消息、输入 @ 选择技能或 / 选择文件"
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  bordered={false}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  disabled={isLoading}
                  style={{
                    padding: '0',
                    fontSize: '14px',
                    resize: 'none',
                    lineHeight: '1.5',
                    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                    background: 'transparent',
                    width: '100%',
                    minHeight: '42px'
                  }}
                />
                
                {/* 输入提示文字 - 只在输入框为空时显示 */}
                {!inputValue && (
                  <div style={{
                    position: 'absolute',
                    bottom: '4px',
                    right: '0',
                    fontSize: '11px',
                    color: '#9ca3af',
                    pointerEvents: 'none',
                    background: 'rgba(255, 255, 255, 0.8)',
                    padding: '2px 4px',
                    borderRadius: '4px'
                  }}>
                    按 Enter 发送 • Shift + Enter 换行
                  </div>
                )}
              </div>
              
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleSendMessage}
                disabled={isLoading || !inputValue.trim()}
                style={{
                  borderRadius: '12px',
                  height: '32px',
                  width: '32px',
                  padding: 0,
                  background: inputValue.trim() 
                    ? '#6366f1' 
                    : '#f1f5f9',
                  borderColor: inputValue.trim() 
                    ? '#6366f1' 
                    : '#f1f5f9',
                  color: inputValue.trim() 
                    ? '#ffffff' 
                    : '#9ca3af',
                  transition: 'all 0.2s ease',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

export default ChatInterface; 