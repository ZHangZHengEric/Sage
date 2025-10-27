import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { tomorrow } from 'react-syntax-highlighter/dist/esm/styles/prism';
import ReactECharts from 'echarts-for-react';
import MessageAvatar from './MessageAvatar';
import MessageTypeLabel from './MessageTypeLabel';
import TokenUsage from './TokenUsage';
import { useLanguage } from '../../contexts/LanguageContext';
import './MessageRenderer.css';

const MessageRenderer = ({ message, onDownloadFile, onToolClick, onTokenUsage, messages, messageIndex, isRestoringHistory }) => {
  const { t } = useLanguage();
  const processedTokenUsageRef = useRef(new Set());
  
  // 参数验证
  if (!message) {
    return null;
  }
  
  // 调试日志已移除

  // 格式化消息内容
  const formatMessageContent = (content) => {
    if (!content) return '';
    
    // 处理工具调用结果的特殊格式
    if (typeof content === 'object') {
      return JSON.stringify(content, null, 2);
    }
    
    return content;
  };

  // 渲染用户消息
  const renderUserMessage = () => (
    <div className="message user-message">
      <MessageAvatar messageType={message.type || message.message_type} role="user" />
      <div className="message-content">
        <MessageTypeLabel messageType={message.type || message.message_type} role="user" type={message.type} />
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatMessageContent(message.content)}</ReactMarkdown>
      </div>
    </div>
  );

  // 渲染AI助手消息
  const renderAssistantMessage = () => {
    // 对于非工具的消息，只显示show_content，如果show_content为空则不显示消息气泡
    if (!message.show_content) {
      return null;
    }
    
    return (
      <div className="message assistant-message">
        <MessageAvatar messageType={message.type || message.message_type} role="assistant" />
        <div className="message-content">
          <MessageTypeLabel messageType={message.type || message.message_type} role="assistant" type={message.type} />
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ node, inline, className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || '');
                const language = match ? match[1] : '';
                
                // 处理 ECharts 代码块
                if (!inline && (language === 'echarts' || language === 'echart')) {
                  try {
                    const chartOption = JSON.parse(String(children).replace(/\n$/, ''));
                    return (
                      <div className="echarts-container" style={{ margin: '10px 0' }}>
                        <ReactECharts
                          option={chartOption}
                          style={{ height: '400px', width: '100%' }}
                          opts={{ renderer: 'canvas' }}
                        />
                      </div>
                    );
                  } catch (error) {
                    return (
                      <div className="echarts-error" style={{ 
                        padding: '10px', 
                        backgroundColor: '#fee', 
                        border: '1px solid #fcc',
                        borderRadius: '4px',
                        color: '#c33'
                      }}>
                        <strong>ECharts 配置错误:</strong> {error.message}
                        <pre style={{ marginTop: '8px', fontSize: '12px' }}>
                          {String(children).replace(/\n$/, '')}
                        </pre>
                      </div>
                    );
                  }
                }
                
                // 处理其他代码块
                return !inline && match ? (
                  <SyntaxHighlighter
                    style={tomorrow}
                    language={language}
                    PreTag="div"
                    {...props}
                  >
                    {String(children).replace(/\n$/, '')}
                  </SyntaxHighlighter>
                ) : (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              }
            }}
          >
            {message.show_content}
          </ReactMarkdown>
        </div>
      </div>
    );
  };

  // 渲染错误消息
  const renderErrorMessage = () => (
    <div className="message error-message">
      <MessageAvatar messageType="error" role={message.role} />
      <div className="message-content">
        <MessageTypeLabel messageType="error" role={message.role} type={message.type} />
        <div className="error-content">
          <strong>错误:</strong> {message.content}
        </div>
      </div>
    </div>
  );

  // 渲染工具调用按钮
  const renderToolCallButton = (message) => {
    if (!message.tool_calls || !Array.isArray(message.tool_calls)) {
      return null;
    }

    return (
      <div className="message tool-calls">
        <MessageAvatar messageType="tool_call" role="assistant" toolName={message.tool_calls[0]?.function?.name} />
        <div className="message-bubble tool-call-bubble">
          <MessageTypeLabel messageType="tool_call" role="assistant" toolName={message.tool_calls[0]?.function?.name} type={message.type} />
          {message.tool_calls.map((toolCall, index) => {
            // 查找对应的tool结果消息
            const toolResult = messages.find(msg => 
              msg.role === 'tool' && msg.tool_call_id === toolCall.id
            );
            
            return (
              <button 
                key={toolCall.id || index}
                className="tool-call-button"
                onClick={() => onToolClick && onToolClick(toolCall, toolResult)}
              >
                <div className="tool-call-info">
                  <span className="tool-name">{toolCall.function?.name || 'Unknown Tool'}</span>
                  <span className="tool-status">
                    {toolResult ? t('toolCall.completed') : t('toolCall.executing')}
                  </span>
                </div>
                <div className="tool-call-arrow">→</div>
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  // 渲染工具执行气泡
  const renderToolBubble = () => {
    const toolName = message.tool_name || '工具执行';
    const isCompleted = message.status === 'completed' || message.type === 'tool_call_result';
    
    return (
      <div className="message tool-execution">
        <MessageAvatar messageType="tool_execution" role="assistant" toolName={message.tool_name} />
        <div className="tool-execution-bubble">
          <MessageTypeLabel messageType="tool_execution" role="assistant" toolName={message.tool_name} type={message.type} />
          <div className="tool-header">
            <span className="tool-name">{toolName}</span>
            <span className={`tool-status ${isCompleted ? 'completed' : 'running'}`}>
              {isCompleted ? '✓' : '⟳'}
            </span>
          </div>
          
          {message.show_content && (
            <div className="tool-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  code({ node, inline, className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || '');
                    return !inline && match ? (
                      <SyntaxHighlighter
                        style={tomorrow}
                        language={match[1]}
                        PreTag="div"
                        {...props}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    );
                  }
                }}
              >
                {message.show_content}
              </ReactMarkdown>
            </div>
          )}
          
          {message.file_path && (
            <div className="tool-file">
              <button 
                onClick={() => onDownloadFile && onDownloadFile(message.file_path)}
                className="download-button"
              >
                📁 下载文件: {message.file_path.split('/').pop()}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  // 如果是tool消息，不单独渲染（会通过工具调用按钮显示）
  if (message.role === 'tool') {
    return null;
  }
  
  // 根据消息类型渲染不同的组件
  if (message.type === 'error' || message.message_type === 'error') {
    return renderErrorMessage();
  }
  
  // 处理 token 使用信息
  if (message.type === 'token_usage' || message.message_type === 'token_usage') {
    const tokenUsageData = message.metadata?.token_usage;
    // console.log('🎯 MessageRenderer: 收到 token_usage 消息', {
    //   messageId: message.message_id,
    //   sessionId: message.session_id,
    //   tokenUsageData: tokenUsageData,
    //   timestamp: new Date().toISOString()
    // });
    
    if (tokenUsageData) {
      // console.log('✅ MessageRenderer: 渲染 TokenUsage 组件', {
      //   totalTokens: tokenUsageData.total_info?.total_tokens,
      //   stepCount: tokenUsageData.per_step_info?.length || 0
      // });
      
      // 使用 useEffect 延迟调用回调函数，但只处理一次相同的消息
        useEffect(() => {
         // 如果当前正在恢复历史对话，则跳过 onTokenUsage 调用
         if (isRestoringHistory) {
           // console.log('🔄 MessageRenderer: 恢复历史对话中，跳过 onTokenUsage 调用');
           return;
         }
         
         if (onTokenUsage && tokenUsageData && message.session_id) {
           const messageKey = `${message.message_id}_${message.session_id}`;
           
           // 检查是否已经处理过这个消息
           if (processedTokenUsageRef.current.has(messageKey)) {
             // console.log('⏭️ MessageRenderer: 跳过已处理的 token_usage 消息', { messageKey });
             return;
           }
           
           // console.log('🔄 MessageRenderer: 调用 onTokenUsage 回调函数', {
           //   sessionId: message.session_id,
           //   tokenUsageData,
           //   messageKey
           // });
           
           // 标记为已处理
           processedTokenUsageRef.current.add(messageKey);
           
           // 调用回调函数
           onTokenUsage(tokenUsageData, message.session_id);
         }
       }, [message.message_id, message.session_id, onTokenUsage, isRestoringHistory]);
      
      return (
        <div className="message token-usage-message">
          <TokenUsage tokenUsage={tokenUsageData} />
        </div>
      );
    }
    
    console.warn('⚠️ MessageRenderer: token_usage 消息缺少 metadata.token_usage 数据');
    return null;
  }
  
  if (message.role === 'user') {
    if (message.message_type === 'guide')
      return null;
    else
      return renderUserMessage();
  }
  
  if (message.role === 'assistant') {
    // 如果assistant消息包含tool_calls，渲染工具调用按钮
    if (message.tool_calls && Array.isArray(message.tool_calls) && message.tool_calls.length > 0) {
      return (
        <div className="message-container">

          {renderToolCallButton(message)}
        </div>
      );
    }
    return renderAssistantMessage();
  }
  
  if (message.type === 'tool_call' || message.message_type === 'tool_call') {
    return renderToolBubble();
  }
  
  // 默认渲染
  return (
    <div className="message">
      <div className="message-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatMessageContent(message.show_content)}</ReactMarkdown>
      </div>
    </div>
  );
};

export default MessageRenderer;