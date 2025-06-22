import React, { useRef } from 'react';
import { Button, Switch, Input } from 'antd';
import { SendOutlined, ThunderboltOutlined, BranchesOutlined, StopOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  isLoading: boolean;
  useDeepThink: boolean;
  useMultiAgent: boolean;
  onDeepThinkChange: (value: boolean) => void;
  onMultiAgentChange: (value: boolean) => void;
}

const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSend,
  isLoading,
  useDeepThink,
  useMultiAgent,
  onDeepThinkChange,
  onMultiAgentChange
}) => {
  const inputRef = useRef<any>(null);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div style={{ 
      padding: '16px 24px',
      borderTop: '1px solid #f1f5f9',
      background: '#f8fafc'
    }}>
      <div style={{
        width: '100%',
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
          {/* 开关区域 */}
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
                  onChange={onDeepThinkChange}
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
                  onChange={onMultiAgentChange}
                  size="small"
                />
                <BranchesOutlined style={{ color: useMultiAgent ? '#10b981' : '#6b7280', fontSize: '12px' }} />
                智能体协作
              </label>
            </div>
          </div>

          {/* 输入框 */}
          <div style={{
            display: 'flex',
            alignItems: 'flex-end',
            padding: '8px 16px 12px 16px',
            gap: '12px'
          }}>
            <div style={{ flex: 1, position: 'relative' }}>
              <TextArea
                ref={inputRef}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder="发消息、输入 @ 选择技能或 / 选择文件"
                autoSize={{ minRows: 2, maxRows: 6 }}
                bordered={false}
                onKeyDown={handleKeyDown}
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
            </div>
            
            <Button
              type="primary"
              icon={isLoading ? <StopOutlined /> : <SendOutlined />}
              onClick={onSend}
              // 修改disabled逻辑：在加载时总是可点击（用于中断），非加载时需要有内容才能点击
              disabled={!isLoading && !value.trim()}
              style={{
                borderRadius: '12px',
                height: '32px',
                width: '32px',
                padding: 0,
                background: isLoading 
                  ? '#ef4444'
                  : (value.trim() ? '#6366f1' : '#f1f5f9'),
                borderColor: isLoading 
                  ? '#ef4444'
                  : (value.trim() ? '#6366f1' : '#f1f5f9'),
                color: isLoading || value.trim() 
                  ? '#ffffff' 
                  : '#9ca3af',
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0
              }}
              title={isLoading ? '中断对话' : '发送消息'}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatInput; 