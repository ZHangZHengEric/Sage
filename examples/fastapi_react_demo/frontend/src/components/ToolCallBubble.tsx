import React from 'react';
import { Button } from 'antd';
import { 
  ToolOutlined, 
  ClockCircleOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined
} from '@ant-design/icons';
import { ToolCallData } from '../types/toolCall';

interface ToolCallBubbleProps {
  toolCall: ToolCallData;
  onClick: (toolCall: ToolCallData) => void;
  isSelected?: boolean;
}

const ToolCallBubble: React.FC<ToolCallBubbleProps> = ({ 
  toolCall, 
  onClick, 
  isSelected = false 
}) => {
  const getStatusIcon = () => {
    switch (toolCall.status) {
      case 'running':
        return <ClockCircleOutlined />;
      case 'success':
        return <CheckCircleOutlined />;
      case 'error':
        return <ExclamationCircleOutlined />;
      default:
        return <ToolOutlined />;
    }
  };

  const getButtonType = () => {
    if (isSelected) return 'primary';
    switch (toolCall.status) {
      case 'success':
        return 'default';
      case 'error':
        return 'default';
      case 'running':
        return 'default';
      default:
        return 'default';
    }
  };

  return (
    <Button
      type={getButtonType()}
      icon={getStatusIcon()}
      onClick={() => onClick(toolCall)}
      style={{
        marginRight: '8px',
        marginBottom: '4px',
        borderRadius: '6px',
        fontSize: '12px',
        height: '28px',
        display: 'inline-flex',
        alignItems: 'center',
        boxShadow: isSelected ? '0 2px 8px rgba(99, 102, 241, 0.2)' : '0 1px 2px rgba(0, 0, 0, 0.1)'
      }}
      size="small"
    >
      {toolCall.toolName}
    </Button>
  );
};

export default ToolCallBubble; 