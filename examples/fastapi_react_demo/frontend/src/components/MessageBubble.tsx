import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import ReactECharts from 'echarts-for-react';
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
      case 'tool_call':
        return '🔧'; // 工具调用请求
      case 'tool_call_result':
        return '📋'; // 工具执行结果
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

  // 处理消息内容和显示逻辑
  const processMessageContent = () => {
    let displayContent = message.displayContent;
    let shouldShowBubble = true;
    
    if (message.type === 'tool_call' || message.type === 'tool_call_result') {
      // 工具调用相关消息：不显示气泡，只显示按钮
      shouldShowBubble = false;
    } else if (message.toolCalls && message.toolCalls.length > 0) {
      // 其他包含工具调用的消息：过滤重复内容
      displayContent = message.displayContent
        // 移除工具调用标题和描述
        .replace(/🔧\s*\*\*调用工具[：:]\s*.*?\*\*[\s\S]*?(?=\n\n|\n(?=[^\s])|$)/g, '')
        // 移除参数描述
        .replace(/📝\s*\*\*参数\*\*[：:]?[\s\S]*?(?=\n\n|\n(?=[^\s])|$)/g, '')
        // 移除JSON代码块
        .replace(/```json[\s\S]*?```/g, '')
        // 移除工具执行状态信息
        .replace(/⚙️\s*执行工具[\s\S]*?(?=\n\n|\n(?=[^\s])|$)/g, '')
        // 移除多余的换行符
        .replace(/\n{3,}/g, '\n\n')
        .trim();
        
      // 如果过滤后内容为空，显示简洁的提示信息
      if (!displayContent) {
        const toolNames = message.toolCalls.map(tc => tc.name).join(', ');
        displayContent = `🔧 调用了 ${message.toolCalls.length} 个工具: ${toolNames}`;
      }
    } else {
      // 普通消息：检查是否为loading状态
      shouldShowBubble = message.type === 'loading' || displayContent !== '';
    }
    
    return { displayContent, shouldShowBubble };
  };

  const { displayContent, shouldShowBubble } = processMessageContent();

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
        {shouldShowBubble && (
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
                    remarkPlugins={[remarkGfm]}
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

                        // 处理 ECharts 代码块
                        if (match[1] === 'echart') {
                          try {
                            const chartOption = JSON.parse(String(children).replace(/\n$/, ''));
                            return (
                              <div style={{ 
                                margin: '12px 0',
                                borderRadius: '8px',
                                overflow: 'hidden',
                                boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)'
                              }}>
                                <ReactECharts
                                  option={chartOption}
                                  style={{ 
                                    height: '400px',
                                    width: '100%'
                                  }}
                                  opts={{ renderer: 'canvas' }}
                                />
                              </div>
                            );
                          } catch (error) {
                            console.error('ECharts 配置解析失败:', error);
                            return (
                              <div style={{
                                background: '#fff2f0',
                                border: '1px solid #ffccc7',
                                borderRadius: '8px',
                                padding: '12px',
                                margin: '8px 0',
                                color: '#dc2626'
                              }}>
                                <strong>ECharts 渲染错误:</strong> 配置格式不正确
                                <details style={{ marginTop: '8px' }}>
                                  <summary>查看原始配置</summary>
                                  <pre style={{ 
                                    background: '#f5f5f5',
                                    padding: '8px',
                                    borderRadius: '4px',
                                    marginTop: '8px',
                                    fontSize: '12px',
                                    overflow: 'auto'
                                  }}>
                                    {String(children)}
                                  </pre>
                                </details>
                              </div>
                            );
                          }
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
                      // 表格支持
                      table({children}) {
                        return (
                          <div style={{ 
                            margin: '12px 0',
                            overflowX: 'auto',
                            borderRadius: '8px',
                            border: '1px solid #e5e7eb'
                          }}>
                            <table style={{
                              width: '100%',
                              borderCollapse: 'collapse',
                              fontSize: '13px'
                            }}>
                              {children}
                            </table>
                          </div>
                        );
                      },
                      thead({children}) {
                        return (
                          <thead style={{
                            background: '#f9fafb'
                          }}>
                            {children}
                          </thead>
                        );
                      },
                      tbody({children}) {
                        return <tbody>{children}</tbody>;
                      },
                      tr({children}) {
                        return (
                          <tr style={{
                            borderBottom: '1px solid #e5e7eb'
                          }}>
                            {children}
                          </tr>
                        );
                      },
                      th({children}) {
                        return (
                          <th style={{
                            padding: '8px 12px',
                            textAlign: 'left',
                            fontWeight: 600,
                            color: '#374151',
                            borderRight: '1px solid #e5e7eb'
                          }}>
                            {children}
                          </th>
                        );
                      },
                      td({children}) {
                        return (
                          <td style={{
                            padding: '8px 12px',
                            borderRight: '1px solid #e5e7eb',
                            color: '#6b7280'
                          }}>
                            {children}
                          </td>
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
        )}
        
        {/* 工具调用按钮 */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div style={{ 
            marginTop: shouldShowBubble ? '8px' : '0px',
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
      </div>
    </div>
  );
};

export default MessageBubble; 