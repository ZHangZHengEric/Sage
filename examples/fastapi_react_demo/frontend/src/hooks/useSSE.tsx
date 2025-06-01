import { useState, useEffect, useRef } from 'react';

interface UseSSEProps {
  url: string;
  onMessage?: (data: any) => void;
  onError?: (error: Event) => void;
}

export const useSSE = ({ url, onMessage, onError }: UseSSEProps) => {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<MessageEvent | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const connectSSE = () => {
      try {
        console.log('连接SSE:', url);
        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.onopen = () => {
          console.log('SSE连接成功');
          setConnected(true);
          setConnectionError(null);
        };

        eventSource.onmessage = (event) => {
          console.log('收到SSE消息:', event.data);
          setLastMessage(event);
          if (onMessage) {
            onMessage(JSON.parse(event.data));
          }
        };

        eventSource.onerror = (error) => {
          console.error('SSE连接错误:', error);
          setConnected(false);
          setConnectionError('SSE连接失败');
          if (onError) {
            onError(error);
          }
        };

      } catch (error) {
        console.error('创建SSE连接失败:', error);
        setConnectionError('无法创建SSE连接');
      }
    };

    connectSSE();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [url, onMessage, onError]);

  // 发送消息的函数 - 通过HTTP POST
  const sendMessage = async (data: any) => {
    try {
      const response = await fetch('/api/chat-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      return response;
    } catch (error) {
      console.error('发送消息失败:', error);
      throw error;
    }
  };

  return {
    connected,
    lastMessage,
    connectionError,
    sendMessage
  };
}; 