import { useState, useRef, useCallback } from 'react';

export const useMessages = () => {
  const [messages, setMessages] = useState([]);
  const [messageChunks, setMessageChunks] = useState(new Map());
  const [isLoading, setIsLoading] = useState(false);
  const [inputMessage, setInputMessage] = useState('');
  const abortControllerRef = useRef(null);

  // 处理分块消息合并
  const handleChunkMessage = useCallback((messageData) => {
    console.log('🧩 收到分块消息:', messageData.type, messageData);
    
    setMessageChunks(prevChunks => {
      const newChunks = new Map(prevChunks);
      // 使用message_id作为分组标识符，而不是chunk_id
      const messageId = messageData.message_id;
      
      if (messageData.type === 'chunk_start') {
        console.log('🚀 开始接收分块消息:', messageId, '总块数:', messageData.total_chunks);
        // 初始化chunk数据收集
        newChunks.set(messageId, {
          chunks: [],
          total_chunks: messageData.total_chunks,
          original_type: messageData.original_type,
          message_id: messageData.message_id,
          received_chunks: 0
        });
      } else if (messageData.type === 'json_chunk') {
        console.log('📦 收到数据块:', messageData.chunk_index + 1, '/', messageData.total_chunks);
        // 收集json_chunk数据
        const existing = newChunks.get(messageId);
        if (existing) {
          // 检查是否已经收到过这个chunk_index，避免重复
          const isDuplicate = existing.chunks.some(chunk => chunk.chunk_index === messageData.chunk_index);
          if (!isDuplicate) {
            existing.chunks.push(messageData);
            existing.received_chunks = existing.chunks.length;
            console.log('📊 已收到块数:', existing.received_chunks, '/', existing.total_chunks);
          } else {
            console.warn('⚠️ 收到重复的chunk_index:', messageData.chunk_index, '忽略');
          }
        } else {
          console.warn('⚠️ 收到chunk但没有找到对应的chunk_start:', messageId);
          // 创建新的chunk收集器（容错处理）
          newChunks.set(messageId, {
            chunks: [messageData],
            total_chunks: messageData.total_chunks,
            message_id: messageId,
            received_chunks: 1
          });
        }
      } else if (messageData.type === 'chunk_end') {
        console.log('🏁 分块传输结束:', messageId);
        // chunk_end时重组完整消息
        const chunkData = newChunks.get(messageId);
        if (chunkData) {
          console.log('🔧 重组消息: 收到', chunkData.received_chunks, '块，期望', chunkData.total_chunks, '块');
          
          try {
            // 按chunk_index排序分块数据
            const sortedChunks = chunkData.chunks.sort((a, b) => a.chunk_index - b.chunk_index);
            
            // 拼接所有分块数据
            const completeData = sortedChunks.map(chunk => chunk.chunk_data).join('');
            console.log('📄 完整数据长度:', completeData.length, '字符');
            
            // 解析完整的JSON数据
            const fullData = JSON.parse(completeData);
            console.log('✅ 成功解析分块JSON数据:', fullData.type || fullData.message_type);
            
            // 使用handleMessage处理重组后的完整消息
            const completeMessage = {
              ...fullData,
              timestamp: messageData.timestamp || Date.now()
            };
            
            // 直接调用handleMessage处理完整消息
            setTimeout(() => {
              handleMessage(completeMessage);
            }, 0);
            
            // 清理chunk数据
            newChunks.delete(messageId);
            console.log('🧹 清理分块数据完成');
          } catch (parseError) {
            console.error('❌ 解析分块数据失败:', parseError);
            console.error('📄 分块详情:', chunkData.chunks.map(c => `索引${c.chunk_index}:${c.chunk_data?.length || 0}字符`));
          }
        } else {
          console.warn('⚠️ chunk_end但没有找到对应的chunk数据:', messageId);
        }
      }
      
      return newChunks;
    });
  }, []);

  // 处理普通消息
  const handleMessage = useCallback((messageData) => {
    setMessages(prevMessages => {
      const newMessages = [...prevMessages];
      const messageId = messageData.message_id;
      
      // 查找是否已存在相同 message_id 的消息
      const existingIndex = newMessages.findIndex(
        msg => msg.message_id === messageId
      );
      
      if (existingIndex >= 0) {
        // 更新现有消息
        const existing = newMessages[existingIndex];
        
        // 对于工具调用结果消息，完整替换而不是合并
        if (messageData.role === 'tool' || messageData.message_type === 'tool_call_result') {
          newMessages[existingIndex] = {
            ...messageData,
            timestamp: messageData.timestamp || Date.now()
          };
        } else {
          // 对于其他消息类型，合并show_content和content
          newMessages[existingIndex] = {
            ...existing,
            ...messageData,
            show_content: (existing.show_content || '') + (messageData.show_content || ''),
            content: (existing.content || '') + (messageData.content || ''),
            timestamp: messageData.timestamp || Date.now()
          };
        }
      } else {
        // 添加新消息
        newMessages.push({
          ...messageData,
          timestamp: messageData.timestamp || Date.now()
        });
      }
      
      return newMessages;
    });
  }, []);

  // 添加用户消息
  const addUserMessage = useCallback((content) => {
    const userMessage = {
      role: 'user',
      content: content.trim(),
      message_id: Date.now().toString(),
      type: 'normal'
    };
    
    setMessages(prev => [...prev, userMessage]);
    return userMessage;
  }, []);

  // 添加错误消息
  const addErrorMessage = useCallback((error) => {
    const errorMessage = {
      role: 'assistant',
      content: `错误: ${error.message}`,
      message_id: Date.now().toString(),
      type: 'error',
      timestamp: Date.now()
    };
    
    setMessages(prev => [...prev, errorMessage]);
  }, []);

  // 清空消息
  const clearMessages = useCallback(() => {
    setMessages([]);
    setMessageChunks(new Map());
  }, []);

  // 停止生成
  const stopGeneration = useCallback(async (currentSessionId) => {
    if (abortControllerRef.current) {
      console.log('Aborting request in stopGeneration');
      abortControllerRef.current.abort();
      setIsLoading(false);
    }
    
    // 调用后端interrupt接口
    if (currentSessionId) {
      try {
        await fetch(`/api/sessions/${currentSessionId}/interrupt`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: '用户请求中断'
          })
        });
        console.log('Session interrupted successfully');
      } catch (error) {
        console.error('Error interrupting session:', error);
      }
    }
  }, []);

  return {
    messages,
    setMessages,
    messageChunks,
    isLoading,
    setIsLoading,
    inputMessage,
    setInputMessage,
    abortControllerRef,
    handleChunkMessage,
    handleMessage,
    addUserMessage,
    addErrorMessage,
    clearMessages,
    stopGeneration
  };
};