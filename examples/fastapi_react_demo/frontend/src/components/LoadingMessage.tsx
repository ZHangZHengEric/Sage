import React from 'react';

interface LoadingMessageProps {
  message: string;
}

const LoadingMessage: React.FC<LoadingMessageProps> = ({ message }) => {
  // 彻底清理消息文字，移除所有可能的点符号
  let cleanMessage = message
    .replace(/\.\.\./g, '')     // 移除三个点
    .replace(/…/g, '')          // 移除省略号
    .replace(/\./g, '')         // 移除所有点
    .replace(/。/g, '')         // 移除中文句号
    .trim();
  
  // 如果消息是"正在回复"，改为"正在思考"
  if (cleanMessage.includes('正在回复')) {
    cleanMessage = cleanMessage.replace('正在回复', '正在思考');
  }
  
  // 确保显示合适的文字
  if (!cleanMessage || cleanMessage.length === 0) {
    cleanMessage = '正在思考';
  }
  
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      <div className="loading-circles" style={{
        display: 'flex',
        gap: '2px'
      }}>
        <div style={{
          width: '4px',
          height: '4px',
          borderRadius: '50%',
          background: '#8b5cf6',
          animation: 'loadingDot 1.4s infinite ease-in-out'
        }}></div>
        <div style={{
          width: '4px',
          height: '4px',
          borderRadius: '50%',
          background: '#8b5cf6',
          animation: 'loadingDot 1.4s infinite ease-in-out 0.2s'
        }}></div>
        <div style={{
          width: '4px',
          height: '4px',
          borderRadius: '50%',
          background: '#8b5cf6',
          animation: 'loadingDot 1.4s infinite ease-in-out 0.4s'
        }}></div>
      </div>
      <span style={{ fontStyle: 'italic', opacity: 0.8 }}>{cleanMessage}</span>
    </div>
  );
};

export default LoadingMessage; 