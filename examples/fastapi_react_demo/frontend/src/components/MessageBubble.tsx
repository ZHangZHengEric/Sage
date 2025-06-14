import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import LoadingMessage from './LoadingMessage';
import ToolCallBubble from './ToolCallBubble';
import { Message, ToolCall } from '../types/chat';

interface MessageBubbleProps {
  message: Message;
  onToolCallClick?: (toolCall: ToolCall) => void;
}

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onToolCallClick }) => {
  const isUser = message.role === 'user';
  const isError = message.type === 'error';
  
  const formatDuration = (duration: number): string => {
    if (duration === 0) {
      return '<1ms';
    }
    if (duration < 1000) {
      return `${Math.max(1, Math.round(duration))}ms`;
    } else {
      return `${(duration / 1000).toFixed(1)}s`;
    }
  };

  // 根据消息类型返回对应的emoji
  const getMessageTypeEmoji = (type: string | undefined): string => {
    if (!type) return '';
    
    switch (type) {
      case 'task_analysis_result':
        return '🔍'; // 任务分析
      case 'task_decomposition':
        return '📋'; // 任务分解
      case 'planning_result':
        return '🎯'; // 规划制定
      case 'observation_result':
        return '👁️'; // 观察结果
      case 'do_subtask_result':
        return '⚙️'; // 子任务执行
      case 'final_answer':
        return '✅'; // 最终答案
      case 'loading':
        return '🤔'; // 思考中
      case 'error':
        return '❌'; // 错误
      case 'thinking':
        return '💭'; // 思考过程
      case 'reflection':
        return '🪞'; // 反思
      case 'decision':
        return '🎲'; // 决策
      case 'execution':
        return '🚀'; // 执行
      case 'validation':
        return '✔️'; // 验证
      case 'summary':
        return '📄'; // 总结
      default:
        return ''; // 普通消息不显示emoji
    }
  };

  return (
    <div
      className="message-bubble"
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: '12px'
      }}
    >
      <div style={{
        maxWidth: isUser ? '75%' : '95%',
        minWidth: '120px',
        position: 'relative'
      }}>
        {/* 智能体类型标签 */}
        {!isUser && message.agentType && message.agentType !== 'Zavix' && (
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
        {(() => {
          // 处理工具调用内容过滤
          let displayContent = message.displayContent;
          if (message.toolCalls && message.toolCalls.length > 0) {
            displayContent = message.displayContent
              .replace(/🔧\s*\*\*调用工具：.*?\*\*[\s\S]*?(?=\n\n|\n$|$)/g, '')
              .replace(/📝\s*\*\*参数\*\*:[\s\S]*?(?=\n\n|\n$|$)/g, '')
              .replace(/```json[\s\S]*?```/g, '')
              .trim();
          }
          
          // 如果内容为空且不是loading状态，不显示消息气泡
          const shouldShowBubble = message.type === 'loading' || displayContent !== '';
          
          if (!shouldShowBubble) {
            return null;
          }
          
          return (
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
              {message.type === 'loading' ? (
                <LoadingMessage message={message.displayContent} />
              ) : (
                <div>
                  {/* 消息类型emoji */}
                  {!isUser && getMessageTypeEmoji(message.type) && (
                    <span style={{
                      fontSize: '16px',
                      marginRight: '8px',
                      display: 'inline-block',
                      verticalAlign: 'top'
                    }}>
                      {getMessageTypeEmoji(message.type)}
                    </span>
                  )}
                  <div style={{ display: 'inline-block', width: !isUser && getMessageTypeEmoji(message.type) ? 'calc(100% - 24px)' : '100%' }}>
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
                              margin: '4px 0', 
                              paddingLeft: '16px',
                              listStyleType: 'disc'
                            }}>
                              {children}
                            </ul>
                          );
                        },
                        ol({children}) {
                          return (
                            <ol style={{ 
                              margin: '4px 0', 
                              paddingLeft: '16px',
                              listStyleType: 'decimal'
                            }}>
                              {children}
                            </ol>
                          );
                        },
                        blockquote({children}) {
                          return (
                            <blockquote style={{
                              borderLeft: '3px solid #e5e7eb',
                              paddingLeft: '12px',
                              margin: '8px 0',
                              fontStyle: 'italic',
                              color: '#6b7280'
                            }}>
                              {children}
                            </blockquote>
                          );
                        }
                      }}
                    >
                      {displayContent}
                    </ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          );
        })()}
        
        {/* 时间戳和耗时 */}
        <div style={{ 
          fontSize: '11px', 
          color: '#9ca3af',
          marginTop: '4px',
          textAlign: isUser ? 'right' : 'left',
          display: 'flex',
          justifyContent: isUser ? 'flex-end' : 'flex-start',
          alignItems: 'center',
          gap: '8px'
        }}>
          <span>
            {message.timestamp.toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit'
            })}
          </span>
          {!isUser && message.type !== 'loading' && message.duration !== undefined && message.duration >= 0 && (
            <span style={{
              background: 'rgba(0, 0, 0, 0.05)',
              padding: '1px 4px',
              borderRadius: '3px',
              fontSize: '10px'
            }}>
              {formatDuration(message.duration)}
            </span>
          )}
        </div>
        
        {/* 工具调用 */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div style={{ 
            marginTop: '8px',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '6px'
          }}>
            {message.toolCalls.map((toolCall) => (
              <ToolCallBubble
                key={toolCall.id}
                toolCall={{
                  id: toolCall.id,
                  toolName: toolCall.name,
                  parameters: toolCall.arguments,
                  result: toolCall.result,
                  duration: toolCall.duration,
                  status: toolCall.status,
                  error: toolCall.error,
                  timestamp: message.timestamp
                }}
                onClick={(toolCallData) => onToolCallClick?.(toolCall)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble; 