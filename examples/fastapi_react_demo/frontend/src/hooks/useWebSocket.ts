import { useState, useEffect, useRef, useCallback } from 'react';

export interface WebSocketMessage {
  data: string;
  type?: string;
}

export interface UseWebSocketOptions {
  reconnectAttempts?: number;
  reconnectInterval?: number;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
}

export const useWebSocket = (
  url: string,
  options: UseWebSocketOptions = {}
) => {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [connected, setConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = options.reconnectAttempts || 5;
  const reconnectInterval = options.reconnectInterval || 3000;
  const isConnecting = useRef(false);
  
  const connect = useCallback(() => {
    // 防止重复连接
    if (isConnecting.current || (socket && socket.readyState === WebSocket.OPEN)) {
      return;
    }
    
    isConnecting.current = true;
    
    try {
      console.log('正在建立WebSocket连接:', url);
      const ws = new WebSocket(url);
      
      ws.onopen = () => {
        console.log('WebSocket连接已建立');
        setConnected(true);
        setConnectionError(null);
        reconnectAttempts.current = 0;
        isConnecting.current = false;
        if (options.onOpen) options.onOpen();
      };
      
      ws.onmessage = (event) => {
        setLastMessage({ data: event.data });
      };
      
      ws.onclose = (event) => {
        console.log('WebSocket连接已关闭', event.code, event.reason);
        setConnected(false);
        setSocket(null);
        isConnecting.current = false;
        
        if (options.onClose) options.onClose();
        
        // 只有在非正常关闭时才重连
        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          reconnectAttempts.current++;
          console.log(`尝试重连 (${reconnectAttempts.current}/${maxReconnectAttempts})`);
          setTimeout(() => {
            connect();
          }, reconnectInterval);
        } else if (reconnectAttempts.current >= maxReconnectAttempts) {
          setConnectionError('连接失败，已达到最大重连次数');
        }
      };
      
      ws.onerror = (error) => {
        console.error('WebSocket错误:', error);
        setConnectionError('WebSocket连接错误');
        isConnecting.current = false;
        if (options.onError) options.onError(error);
      };
      
      setSocket(ws);
    } catch (error) {
      console.error('创建WebSocket连接失败:', error);
      setConnectionError('无法创建WebSocket连接');
      isConnecting.current = false;
    }
  }, [url, maxReconnectAttempts, reconnectInterval]);
  
  useEffect(() => {
    connect();
    
    return () => {
      isConnecting.current = false;
      reconnectAttempts.current = maxReconnectAttempts; // 阻止重连
      if (socket) {
        socket.close(1000, 'Component unmounting');
      }
    };
  }, [url]); // 只依赖URL变化
  
  const sendMessage = useCallback((message: any) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    } else {
      console.warn('WebSocket未连接，无法发送消息');
    }
  }, [socket]);
  
  const disconnect = useCallback(() => {
    reconnectAttempts.current = maxReconnectAttempts; // 阻止重连
    if (socket) {
      socket.close(1000, 'Manual disconnect');
    }
  }, [socket, maxReconnectAttempts]);
  
  return {
    socket,
    lastMessage,
    connected,
    connectionError,
    sendMessage,
    disconnect,
    reconnect: connect
  };
}; 