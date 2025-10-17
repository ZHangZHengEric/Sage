export const useChatAPI = () => {
  // 发送消息到后端
  const sendMessage = async ({
    message,
    sessionId,
    selectedAgent,
    config,
    abortControllerRef,
    onMessage,
    onChunkMessage,
    onError,
    onComplete
  }) => {
    try {
      // 创建新的 AbortController
      if (abortControllerRef) {
        abortControllerRef.value = new AbortController();
      }
      
      const requestBody = {
        messages: [{
          role: 'user',
          content: message
        }],
        user_id: "default_user",
        session_id: sessionId,
        deep_thinking: config.deepThinking,
        multi_agent: config.multiAgent,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount,
        agent_id: selectedAgent?.id || "default_agent",
        agent_name: selectedAgent?.name || "Sage Assistant",
        system_context: selectedAgent?.systemContext || {},
        available_workflows: selectedAgent?.availableWorkflows || {},
        llm_model_config: selectedAgent?.llmConfig || {
          model: '',
          maxTokens: 4096,
          temperature: 0.7
        },
        system_prefix: selectedAgent?.systemPrefix || 'You are a helpful AI assistant.',
        available_tools: selectedAgent?.availableTools || []
      };
      
      // 在浏览器控制台显示聊天时的配置参数
      console.log('📥 传入的config对象:', config);
      console.log('🚀 聊天请求配置参数:', {
        deep_thinking: config.deepThinking,
        multi_agent: config.multiAgent,
        more_suggest: config.moreSuggest,
        max_loop_count: config.maxLoopCount
      });  
      const response = await fetch('/api/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
        signal: abortControllerRef?.value?.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let messageCount = 0;

      console.log('🌊 开始读取WebSocket流数据');

      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          console.log('📡 WebSocket流读取完成，总共处理', messageCount, '条消息');
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // 保留不完整的行

        for (const line of lines) {
          if (line.trim() === '') continue;
          
          messageCount++;
          
          try {
            const messageData = JSON.parse(line);
            
            // 处理分块消息
            if (messageData.type === 'chunk_start' || 
                messageData.type === 'json_chunk' || 
                messageData.type === 'chunk_end') {
              console.log('🧩 分块消息:', messageData.type, messageData);
              if (onChunkMessage) {
                onChunkMessage(messageData);
              }
         
            } else {
              // 处理普通消息
              if (onMessage) {
                onMessage(messageData);
              }
          
            }
          } catch (parseError) {
            console.error('❌ JSON解析失败:', parseError);
            console.error('📄 原始行内容:', line);
          }
        }
      }
      
      onComplete();
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('Request was aborted');
      } else {
        console.error('Error sending message:', error);
        onError(error);
      }
    }
  };

  // 中断会话
  const interruptSession = async (sessionId) => {
    if (!sessionId) return;
    
    try {
      await fetch(`/api/sessions/${sessionId}/interrupt`, {
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
  };

  return {
    sendMessage,
    interruptSession
  };
};