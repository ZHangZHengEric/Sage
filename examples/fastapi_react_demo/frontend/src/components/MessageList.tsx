import React from 'react';
import { Collapse } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import MessageBubble from './MessageBubble';
import WelcomeScreen from './WelcomeScreen';
import { Message, ToolCall, ChatSettings } from '../types/chat';

const { Panel } = Collapse;

interface MessageListProps {
  messages: Message[];
  onExampleClick: (example: string) => void;
  onToolCallClick?: (toolCall: ToolCall) => void;
  settings?: ChatSettings; // 添加设置信息
}

interface MessageGroup {
  userMessage: Message;
  thinkingMessages: Message[];
  finalMessage?: Message;
}

const MessageList: React.FC<MessageListProps> = ({ messages, onExampleClick, onToolCallClick, settings }) => {
  // 对消息进行分组处理
  const groupMessages = (messages: Message[]): (Message | MessageGroup)[] => {
    const groups: (Message | MessageGroup)[] = [];
    let currentGroup: MessageGroup | null = null;
    
    // 根据设置决定分组规则
    const useMultiAgent = settings?.useMultiAgent || false;
    const useDeepThink = settings?.useDeepThink || false;
    
    for (const message of messages) {
      if (message.role === 'user') {
        // 用户消息开始新的分组
        if (currentGroup) {
          groups.push(currentGroup);
        }
        currentGroup = {
          userMessage: message,
          thinkingMessages: [],
          finalMessage: undefined
        };
      } else if (message.role === 'assistant' && message.type !== 'loading') {
        if (currentGroup) {
          // 根据设置决定消息分组
          let shouldPutInThinking = false;
          let isFinalAnswer = false;
          
          if (useMultiAgent) {
            // 多智能体协作模式：final_answer在外面，其他都在思考过程框内
            isFinalAnswer = message.type === 'final_answer';
            shouldPutInThinking = !isFinalAnswer;
          } else if (useDeepThink) {
            // 深度思考模式：只有task_analysis_result放到思考过程，其他都在外面
            shouldPutInThinking = message.type === 'task_analysis_result';
            isFinalAnswer = false; // 深度思考模式下没有特殊的final answer
          } else {
            // 普通模式：都在外面，没有思考过程
            shouldPutInThinking = false;
            isFinalAnswer = false;
          }
          
          if (isFinalAnswer && !currentGroup.finalMessage) {
            currentGroup.finalMessage = message;
          } else if (shouldPutInThinking) {
            currentGroup.thinkingMessages.push(message);
          } else {
            // 作为独立消息显示在外面
            // 先完成当前用户消息组（如果有内容的话）
            if (currentGroup.thinkingMessages.length > 0 || currentGroup.finalMessage) {
              groups.push(currentGroup);
            } else {
              // 如果当前组没有思考内容，只保留用户消息
              groups.push(currentGroup.userMessage);
            }
            // 添加当前助手消息作为独立消息
            groups.push(message);
            currentGroup = null;
          }
        } else {
          // 独立的助手消息
          groups.push(message);
        }
      } else {
        // 系统消息、loading消息等其他类型
        if (message.type === 'loading') {
          // loading消息关联到当前用户消息组，不作为独立消息
          if (currentGroup) {
            // 将loading消息作为思考消息添加到当前组
            currentGroup.thinkingMessages.push(message);
          } else {
            // 如果没有当前组，作为独立消息添加（应该很少见）
            groups.push(message);
          }
        } else {
          if (currentGroup) {
            groups.push(currentGroup);
            currentGroup = null;
          }
          groups.push(message);
        }
      }
    }
    
    // 添加最后的分组
    if (currentGroup) {
      groups.push(currentGroup);
    }
    
    return groups;
  };

  const groupedMessages = groupMessages(messages);

  const renderGroup = (group: Message | MessageGroup, index: number) => {
    if ('userMessage' in group) {
      // 这是一个消息组
      const { userMessage, thinkingMessages, finalMessage } = group;
      
      // 分离loading消息和其他思考消息
      const loadingMessages = thinkingMessages.filter(msg => msg.type === 'loading');
      const actualThinkingMessages = thinkingMessages.filter(msg => msg.type !== 'loading');
      
      return (
        <div key={`group-${index}`}>
          {/* 用户消息 */}
          <MessageBubble 
            message={userMessage} 
            onToolCallClick={onToolCallClick}
          />
          
          {/* Loading消息 - 显示在用户消息下方，思考过程外面 */}
          {loadingMessages.map((loadingMessage) => (
            <div key={loadingMessage.id} style={{ marginBottom: '12px' }}>
              <MessageBubble 
                message={loadingMessage} 
                onToolCallClick={onToolCallClick}
              />
            </div>
          ))}
          
          {/* 深度思考过程 */}
          {actualThinkingMessages.length > 0 && (
            <div style={{
              marginBottom: '12px',
              display: 'flex',
              justifyContent: 'flex-start'
            }}>
              <div style={{
                maxWidth: '95%',
                minWidth: '120px'
              }}>
                {/* 智能体类型标签 */}
                <div style={{
                  fontSize: '12px',
                  color: '#8b5cf6',
                  marginBottom: '4px',
                  fontWeight: 500
                }}>
                  深度思考
                </div>
                
                {/* 深度思考折叠面板 */}
                <Collapse
                  className="deep-think-collapse"
                  style={{
                    background: '#f8fafc',
                    border: '1px solid #e2e8f0',
                    borderRadius: '16px',
                    boxShadow: '0 2px 8px rgba(139, 92, 246, 0.1)'
                  }}
                  expandIconPosition="end"
                  defaultActiveKey={['thinking']}
                >
                  <Panel 
                    header={
                      <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: '#8b5cf6'
                      }}>
                        <ThunderboltOutlined />
                        <span style={{ fontWeight: 500 }}>思考过程</span>
                      </div>
                    }
                    key="thinking"
                  >
                    <div style={{
                      maxHeight: '400px',
                      overflowY: 'auto',
                      padding: '8px'
                    }}>
                      {actualThinkingMessages.map((thinkMessage) => (
                        <div key={thinkMessage.id} style={{ 
                          marginBottom: '8px',
                          width: '100%'  // 让内部气泡占满可用宽度
                        }}>
                          <MessageBubble 
                            message={thinkMessage} 
                            onToolCallClick={onToolCallClick}
                          />
                        </div>
                      ))}
                    </div>
                  </Panel>
                </Collapse>
                
                {/* 时间戳 */}
                <div style={{ 
                  fontSize: '11px', 
                  color: '#9ca3af',
                  marginTop: '4px',
                  textAlign: 'left'
                }}>
                  {actualThinkingMessages[actualThinkingMessages.length - 1]?.timestamp.toLocaleTimeString('zh-CN', {
                    hour: '2-digit',
                    minute: '2-digit'
                  })}
                </div>
              </div>
            </div>
          )}
          
          {/* 最终回答 */}
          {finalMessage && (
            <MessageBubble 
              message={finalMessage} 
              onToolCallClick={onToolCallClick}
            />
          )}
        </div>
      );
    } else {
      // 这是一个独立消息
      return (
        <MessageBubble 
          key={group.id}
          message={group} 
          onToolCallClick={onToolCallClick}
        />
      );
    }
  };

  return (
    <div style={{
      flex: 1,
      overflowY: 'auto',
      padding: '20px 24px',
      background: '#f8fafc'
    }}>
      <div style={{
        maxWidth: '768px',
        margin: '0 auto'
      }}>
        {messages.length === 0 ? (
          <WelcomeScreen onExampleClick={onExampleClick} />
        ) : (
          <div>
            {groupedMessages.map((group, index) => renderGroup(group, index))}
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageList; 